#!/usr/bin/env python3
"""推送提示词到 Langfuse（单向：git → Langfuse，不拉回）。

无 [user] 段补一条 chat user 消息（UI Prompt Experiment 只支持单轮，要求 prompt 变量名与
dataset item 键同名）；system 段一字不改。它不跑 LangGraph 图，链路回归用 langfuse_eval.py。

退出码：0 成功 / 1 目标不存在或内容无效 / 2 配置缺失或网络问题
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.prompts import _langfuse_name, _parse_prompt_md  # noqa: E402
from scripts.langfuse._public_api import load_dotenv  # noqa: E402

load_dotenv()

PROMPTS_ROOT = PROJECT_ROOT / "app" / "prompts"

#: 默认只打 staging 标签。运行时 load_prompt 读的是 production 标签，
#: 所以打 staging 不会劫持应用行为——要生效必须显式 --label production。
DEFAULT_LABEL = "staging"

#: 无 [user] 段的提示词补这条 user 消息。两个理由：
#: 1. 为什么补 —— UI Prompt Experiment 要求 prompt 里有变量、且名字与 dataset item 的键
#:    相同，而本项目提示词的 system 段没有任何占位符（用户输入是运行时由
#:    blocks.source_payload() 拼出来的）。
#: 2. 为什么是这个形状 —— 必须与 source_payload() 的首轮输出同形，否则提示词里
#:    「evidence 取自 sources.raw」「sources.quote 只能补充上下文」那类规则会失效。
#: {{send_text}} 是给 Langfuse 解析的占位符，对应 dataset item input 的顶层键 send_text。
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


def _read_workspace_prompt(category: str, name: str) -> tuple[str, str, Path]:
    """直接读工作区的 .md（不经过 load_prompt，避免被 Langfuse 侧内容反向污染）。"""
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


def _build_prompt_body(system: str, user_template: str) -> list[dict[str, str]]:
    """拼 chat 消息：有 [user] 段用 git 的模板，否则补 EXPERIMENT_USER_TEMPLATE。

    system 段始终是 git 原文。与 app/prompts/__init__.py::_load_from_langfuse 的
    反序列化契约（list → 按 role 取 system / user）一一对应。
    """
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_template or EXPERIMENT_USER_TEMPLATE},
    ]


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
    parser.add_argument("--dry-run", action="store_true", help="不推送，只打印将上传的内容摘要")
    args = parser.parse_args()

    category, name = _parse_target(args.target)
    system, user_template, path = _read_workspace_prompt(category, name)
    lf_name = _langfuse_name(category, name)
    body = _build_prompt_body(system, user_template)

    rel = path.relative_to(PROJECT_ROOT)
    # system 太长不打印，user 直接把实际内容打出来（换行转义），一眼能看出推的是什么
    user_line = body[1]["content"].replace("\n", r"\n")
    print(f"源文件    : {rel}")
    print(f"Langfuse  : name={lf_name}  type=chat  label={args.label}")
    print(f"system    : {len(system)} 字符（git 原文）")
    print(f"user      : {user_line}")

    if args.dry_run:
        print()
        print("[dry-run] 未推送。system 段前 200 字符:")
        print("-" * 60)
        print(system[:200])
        print("-" * 60)
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
            type="chat",
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

    experiment_help = f"""
  在 UI 里跑 Prompt Experiment（对应 dataset 需含 send_text 键）：
    1. Datasets → 选数据集 → Start Experiment
    2. Prompt 选 {lf_name}
    3. 变量 {{send_text}} 会自动映射到 dataset item 的 send_text
    4. 结构化输出：打开开关，挂 CloseIntentOutput 的 JSON schema（在 Playground 存过就能选）
    5. 注意：只跑首轮；不跑 LangGraph 图，链路回归仍用 langfuse_eval.py"""

    print(
        f"""
下一步：
  1. Langfuse UI → Prompts → {lf_name}，确认内容
  2. 在 Playground 或 Prompt Experiment 里试跑验证
  3. 要落回代码：直接在 app/prompts/ 里改并走 PR —— 不从 Langfuse 拉取{experiment_help}

注意：
  - 标签是 {args.label}，运行时 load_prompt 读的是 production，应用行为不受影响
  - 要清掉演练版：npx @langfuse/cli api prompts delete {lf_name}（名字是位置参数；不带名字会报错）
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
