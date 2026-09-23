#!/usr/bin/env python3
"""把 git 里的提示词 .md 推到 Langfuse 演练区（ADR 0014 D3 的反方向）。

ADR 0014 D3 的完整闭环：
    1. **本脚本** 把 app/prompts/{category}/{name}.md 推到 Langfuse（label=staging）
    2. 在 Langfuse UI / Playground 里改 + 试跑
    3. staging 跑 harness golden set 验证
    4. promote_langfuse_prompt.py 拉回 app/prompts/{category}/{name}_v{N+1}.md
    5. git commit + PR + review + merge（金融审计屏障）
    6. 生产按 ADR 0003 灰度切换（app/prompts/_versions.yaml）

真源永远是 git 的 .md；本脚本只做单向推送，不读 Langfuse。

## 关于 UI Prompt Experiment

Langfuse UI 的 Prompt Experiment 要求「prompt 里的变量名与 dataset item 的键同名」
（官方文档 experiments-via-ui「Create a usable prompt」）。本项目提示词的 system 段
**没有任何占位符**——用户输入是运行时由 blocks.source_payload() 拼出来的 user 消息。
所以原样上传的 text 提示词在 UI 里会报 `Selected prompt has no variables or placeholders`。

默认行为因此补一条 chat user 消息，形状与 source_payload() 的**首轮**输出一致：

    {"context": {}, "sources": {"quote": "", "raw": "{{send_text}}"}, "source_roles": {}}

这让 dataset 的 send_text 键能映射进来。**system 段一字不改。** 用 --plain 可关掉，
退回「git 的纯镜像」。

**保真边界**（务必知道）：
- UI experiment 只拼 prompt 调模型，**不跑 LangGraph 图**、不执行 source_payload()、
  不调 Java 后端 → 它测的是提示词本身，不是链路回归。链路回归用 langfuse_eval.py。
- 只覆盖**首轮**：第 N 轮的 quote 与 history 依赖前 N-1 轮的回复，静态数据集给不出。
  首轮无引用无历史，所以模板与真实 payload 逐字一致。
- 数据集 input 键必须是 send_text。旧版脚本上传的 otc-option-golden 用的是
  {turns:[{raw_content,...}]}，映射不上。

跑法：
    python scripts/langfuse/upload_prompt_to_langfuse.py option_close.intent --dry-run
    python scripts/langfuse/upload_prompt_to_langfuse.py option_close.intent
    python scripts/langfuse/upload_prompt_to_langfuse.py option_close.intent --plain

退出码：
    0 成功
    1 目标不存在 / 内容无效
    2 配置缺失 / 网络问题
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.prompts import _langfuse_name, _parse_prompt_md  # noqa: E402

PROMPTS_ROOT = PROJECT_ROOT / "app" / "prompts"

#: 默认只打 staging 标签。运行时 load_prompt 读的是 production 标签，
#: 所以打 staging 不会劫持应用行为——要生效必须显式 --label production。
DEFAULT_LABEL = "staging"

#: 无 [user] 段的提示词补这条 user 消息，形状与 blocks.source_payload() 首轮输出一致。
#: {{send_text}} 是给 Langfuse 解析的占位符，对应 dataset item input 的 send_text 键。
EXPERIMENT_USER_TEMPLATE = (
    '{"context": {}, "sources": {"quote": "", "raw": "{{send_text}}"}, "source_roles": {}}'
)


def _parse_target(arg: str) -> tuple[str, str]:
    """`option_close.intent` → ('option_close', 'intent')。"""
    if "." not in arg:
        print(
            f"ERROR: 目标格式应为 `category.name`，如 option_close.intent；收到: {arg!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    category, name = arg.rsplit(".", 1)
    return category, name


def _read_git_prompt(category: str, name: str) -> tuple[str, str, Path]:
    """直接从 git 的 .md 读取（不经过 load_prompt，避免被 Langfuse 侧内容反向污染）。"""
    path = PROMPTS_ROOT / category / f"{name}.md"
    if not path.exists():
        available = sorted(
            f"{d.name}.{f.stem}"
            for d in PROMPTS_ROOT.iterdir()
            if d.is_dir()
            for f in d.glob("*.md")
        )
        print(f"ERROR: 提示词不存在: {path}", file=sys.stderr)
        print(f"可用的目标: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    system, user_template = _parse_prompt_md(path.read_text(encoding="utf-8"))
    if not system.strip():
        print(f"ERROR: {path} 未找到 [system] 段或内容为空", file=sys.stderr)
        sys.exit(1)
    return system, user_template, path


def _build_prompt_body(system: str, user_template: str, experiment: bool):
    """决定上传类型与内容。

    - `.md` 自带 [user] 段 → chat，用 git 的 user 模板（实验与演练一致，无需替换）
    - 无 [user] 段 + experiment → chat，user 用 EXPERIMENT_USER_TEMPLATE
    - 无 [user] 段 + --plain → text，纯 system（UI experiment 会报 no variables）

    与 app/prompts/__init__.py::_load_from_langfuse 的反序列化契约一一对应。
    """
    if user_template:
        return "chat", [
            {"role": "system", "content": system},
            {"role": "user", "content": user_template},
        ], "git 的 [user] 段"
    if experiment:
        return "chat", [
            {"role": "system", "content": system},
            {"role": "user", "content": EXPERIMENT_USER_TEMPLATE},
        ], "实验用 user 模板（source_payload 首轮形状）"
    return "text", system, "纯 system（无 user 段）"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR 0014 D3 · git 提示词 → Langfuse 演练区（单向推送）"
    )
    parser.add_argument("target", help="格式 `category.name`，如 option_close.intent")
    parser.add_argument(
        "--label",
        default=DEFAULT_LABEL,
        help=f"部署标签（默认 {DEFAULT_LABEL}；运行时读 production，慎用）",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="不补实验用 user 消息，上传成纯 system 的 text 提示词（UI experiment 将不可用）",
    )
    parser.add_argument("--dry-run", action="store_true", help="不推送，只打印将上传的内容摘要")
    args = parser.parse_args()

    category, name = _parse_target(args.target)
    system, user_template, path = _read_git_prompt(category, name)
    lf_name = _langfuse_name(category, name)
    prompt_type, body, origin = _build_prompt_body(system, user_template, not args.plain)

    rel = path.relative_to(PROJECT_ROOT)
    print(f"源文件    : {rel}")
    print(f"Langfuse  : name={lf_name}  type={prompt_type}  label={args.label}")
    print(f"内容      : system {len(system)} 字符（原文不改）；user 来自 {origin}")
    if prompt_type == "text":
        print("            ⚠️  text 类型无变量，Langfuse UI 的 Prompt Experiment 会报")
        print("               `Selected prompt has no variables or placeholders`")

    if args.dry_run:
        print("[dry-run] 未推送。system 段前 200 字符:")
        print("-" * 60)
        print(system[:200])
        print("-" * 60)
        if prompt_type == "chat":
            print("[dry-run] user 消息:")
            print(json.dumps(body[1]["content"], ensure_ascii=False))
        return 0

    try:
        from langfuse import Langfuse
    except ImportError:
        print("ERROR: 未安装 langfuse SDK；pip install -e .", file=sys.stderr)
        return 2

    try:
        lf = Langfuse()
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: Langfuse 客户端初始化失败（检查 LANGFUSE_HOST / 密钥）: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        created = lf.create_prompt(
            name=lf_name,
            type=prompt_type,
            prompt=body,
            labels=[args.label],
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: 推送失败: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    version = getattr(created, "version", "?")
    print(f"\n✅ 已推送：{lf_name} 版本 v{version}，标签 [{args.label}]")

    if prompt_type == "chat":
        experiment_help = f"""
  在 UI 里跑 Prompt Experiment（对应 dataset 需含 send_text 键）：
    1. Datasets → 选数据集 → Start Experiment
    2. Prompt 选 {lf_name}
    3. 变量 {{send_text}} 会自动映射到 dataset item 的 send_text
    4. 结构化输出：打开开关，挂 CloseIntentOutput 的 JSON schema（在 Playground 存过就能选）
    5. 注意：只跑首轮；不跑 LangGraph 图，链路回归仍用 langfuse_eval.py"""
    else:
        experiment_help = """
  （--plain：无变量，UI Prompt Experiment 不可用。需要实验请去掉 --plain 重推）"""

    print(
        f"""
下一步：
  1. Langfuse UI → Prompts → {lf_name}，确认内容
  2. 验证通过后拉回 git：
       python scripts/langfuse/promote_langfuse_prompt.py {category}.{name}
  3. git commit + PR review（不要跳过——Langfuse 侧不是生产真源）{experiment_help}

注意：
  - 标签是 {args.label}，运行时 load_prompt 读的是 production，应用行为不受影响
  - 要清掉演练版：npx @langfuse/cli api prompts delete {lf_name}（名字是位置参数；不带名字会报错）
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
