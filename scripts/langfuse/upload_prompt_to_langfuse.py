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

跑法：
    python scripts/langfuse/upload_prompt_to_langfuse.py option_close.intent --dry-run
    python scripts/langfuse/upload_prompt_to_langfuse.py option_close.intent
    python scripts/langfuse/upload_prompt_to_langfuse.py swap.intent --label staging

退出码：
    0 成功
    1 目标不存在 / 内容无效
    2 配置缺失 / 网络问题
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.prompts import _langfuse_name, _parse_prompt_md  # noqa: E402

PROMPTS_ROOT = PROJECT_ROOT / "app" / "prompts"

#: 默认只打 staging 标签。运行时 load_prompt 读的是 production 标签，
#: 所以打 staging 不会劫持应用行为——要生效必须显式 --label production。
DEFAULT_LABEL = "staging"


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


def _build_prompt_body(system: str, user_template: str):
    """有 [user] 段 → chat 类型（system + user 两条消息）；否则 text 类型。

    与 app/prompts/__init__.py::_load_from_langfuse 的反序列化契约一一对应。
    """
    if user_template:
        return "chat", [
            {"role": "system", "content": system},
            {"role": "user", "content": user_template},
        ]
    return "text", system


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
    system, user_template, path = _read_git_prompt(category, name)
    lf_name = _langfuse_name(category, name)
    prompt_type, body = _build_prompt_body(system, user_template)

    rel = path.relative_to(PROJECT_ROOT)
    print(f"源文件    : {rel}")
    print(f"Langfuse  : name={lf_name}  type={prompt_type}  label={args.label}")
    print(f"内容      : system {len(system)} 字符" + (f"，user 模板 {len(user_template)} 字符" if user_template else ""))

    if args.dry_run:
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
    print(
        f"""
下一步：
  1. Langfuse UI → Prompts → {lf_name}，确认内容
  2. 改 prompt / 试跑：{lf_name}（改完会生成新版本）
  3. 验证通过后拉回 git：
       python scripts/langfuse/promote_langfuse_prompt.py {category}.{name}
  4. git commit + PR review（不要跳过——Langfuse 侧不是生产真源）

注意：
  - 标签是 {args.label}，运行时 load_prompt 读的是 production，应用行为不受影响
  - 要清掉演练版：langfuse api prompts delete --prompt-name {lf_name}
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
