#!/usr/bin/env python3
"""ADR 0014 D3 · 从 LangFuse 演练区晋升 prompt 到 git 真理来源。

F4.6 灰度期错例修复流程：
    1. 运维/产品在 LangFuse UI 改 prompt（如 swap_intent v3）
    2. staging 跑 harness golden set 验证
    3. **本脚本** 把 LangFuse 内容拉到 app/prompts/{category}/{name}_v{N+1}.md
    4. 开发者 git commit + PR + review + merge
    5. 生产按 ADR 0003 v1/v2 同目录机制金丝雀切换

跑法：
    python scripts/promote_langfuse_prompt.py swap.intent
    python scripts/promote_langfuse_prompt.py option.extract_inquiry
    python scripts/promote_langfuse_prompt.py swap.intent --version 5  # 强制 _v5

输出 → `app/prompts/{category}/{name}_v{N+1}.md`
退出码：
    0 成功（输出含 git commit 提示）
    1 LangFuse prompt 不存在 / 内容无效
    2 配置缺失 / 网络问题
    3 目标文件已存在（避免覆盖）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 让脚本能直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "app" / "prompts"


def _parse_target(arg: str) -> tuple[str, str]:
    """`swap.intent` → ('swap', 'intent')；支持嵌套类如 `option_close.confirm_close`。"""
    if "." not in arg:
        print(
            f"ERROR: 目标格式应为 `category.name`，如 swap.intent；收到: {arg!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    category, name = arg.rsplit(".", 1)
    return category, name


def _next_version(category: str, name: str) -> int:
    """扫 app/prompts/{category}/{name}_v{N}.md，返回下一个版本号。

    无版本文件（只有 {name}.md）→ 下一个版本是 2。
    """
    category_dir = PROMPTS_ROOT / category
    if not category_dir.exists():
        print(
            f"ERROR: category 目录不存在: {category_dir}",
            file=sys.stderr,
        )
        sys.exit(1)
    base_file = category_dir / f"{name}.md"
    if not base_file.exists():
        print(
            f"ERROR: base prompt 不存在: {base_file}（先在 git 落 v1 再用本脚本晋升）",
            file=sys.stderr,
        )
        sys.exit(1)

    pattern = re.compile(rf"^{re.escape(name)}_v(\d+)\.md$")
    max_ver = 1
    for f in category_dir.iterdir():
        m = pattern.match(f.name)
        if m:
            max_ver = max(max_ver, int(m.group(1)))
    return max_ver + 1


def _langfuse_name(category: str, name: str) -> str:
    """category/name → Langfuse prompt name（与 app/prompts/__init__.py 同款约定）。"""
    return "_".join(category.split("/") + [name])


def _fetch_langfuse_prompt(category: str, name: str) -> tuple[str, int]:
    """从 LangFuse 拉指定 prompt 最新版本。

    Returns:
        (markdown_content, langfuse_version)
    """
    try:
        from langfuse import Langfuse
    except ImportError:
        print(
            "ERROR: 未安装 langfuse SDK；pip install langfuse",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        lf = Langfuse()
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: LangFuse 客户端初始化失败（检查 LANGFUSE_HOST / 密钥）: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    lf_name = _langfuse_name(category, name)
    try:
        prompt = lf.get_prompt(lf_name)
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: 无法拉取 LangFuse prompt `{lf_name}`: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    return _render_markdown_from_langfuse(prompt, lf_name)


def render_prompt_md(title: str, system: str, user_template: str) -> str:
    """按 app/prompts/__init__.py 的解析契约（## [system] / ## [user] + 围栏）渲染 .md。"""
    parts = [f"# {title}", "", "## [system]", "", "```", system, "```", ""]
    if user_template:
        parts += ["## [user]", "", "```", user_template, "```", ""]
    return "\n".join(parts)


def append_manifest_gray(
    manifest_path: Path, category: str, name: str, version: int, base_sha: str, since: str
) -> None:
    """把晋升产物登记为 app/prompts/_manifest.yaml 的 gray 条目（ADR 0022 D2/D3）。

    文本追加而非 yaml.dump 重写，以保留 manifest 里的注释。
    """
    entry = (
        f"  {category}/{name}_v{version}:\n"
        f"    status: gray\n"
        f"    base: {category}/{name}\n"
        f'    since: "{since}"\n'
        f"    base_system_sha256: {base_sha}\n"
    )
    text = manifest_path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    manifest_path.write_text(text + entry, encoding="utf-8")


def _render_markdown_from_langfuse(prompt, lf_name: str) -> tuple[str, int]:
    """把 LangFuse 的 prompt 对象渲染为 markdown 文本（按 app/prompts/__init__.py 反向约定）。

    LangFuse prompt.prompt 可能是：
    - list of {role, content} → 多 message 拼接
    - str → 单一 system 内容
    """
    body = prompt.prompt
    version = getattr(prompt, "version", 0)

    if isinstance(body, list):
        # 多 message 形态 → 提取 system + user_template
        system = ""
        user_template = ""
        for msg in body:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                system = content
            elif role == "user":
                user_template = content
        if not system:
            print(
                f"ERROR: LangFuse prompt `{lf_name}` 缺 system 内容",
                file=sys.stderr,
            )
            sys.exit(1)
        md = render_prompt_md(f"{lf_name} (LangFuse v{version})", system, user_template)
    elif isinstance(body, str):
        if not body.strip():
            print(
                f"ERROR: LangFuse prompt `{lf_name}` 内容为空",
                file=sys.stderr,
            )
            sys.exit(1)
        md = render_prompt_md(f"{lf_name} (LangFuse v{version})", body.strip(), "")
    else:
        print(
            f"ERROR: LangFuse prompt `{lf_name}` 不识别的格式: {type(body).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)

    return md, int(version) if version else 0


def _write_target(
    category: str, name: str, version: int, content: str, force: bool = False
) -> Path:
    """写入 app/prompts/{category}/{name}_v{version}.md。"""
    target = PROMPTS_ROOT / category / f"{name}_v{version}.md"
    if target.exists() and not force:
        print(
            f"ERROR: 目标文件已存在: {target}（用 --force 覆盖，但通常应该用更高版本号）",
            file=sys.stderr,
        )
        sys.exit(3)
    target.write_text(content, encoding="utf-8")
    from datetime import date

    from scripts.prompt_inventory import system_sha256

    manifest = PROMPTS_ROOT / "_manifest.yaml"
    base_md = PROMPTS_ROOT / category / f"{name}.md"
    if manifest.exists() and base_md.exists():
        append_manifest_gray(
            manifest, category, name, version,
            base_sha=system_sha256(base_md), since=date.today().isoformat(),
        )
    return target


def _print_next_steps(
    target: Path, category: str, name: str, version: int, lf_version: int
) -> None:
    rel = target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target
    msg = f"""
✅ 晋升成功

源:   LangFuse prompt `{_langfuse_name(category, name)}` (LangFuse 内部版本 v{lf_version})
目标: {rel}

下一步（开发者）：
  1. 检查内容: less {rel}
  2. 跑 harness 验证: python -m harness run --category {category}/
  3. 提交:
     git add {rel}
     git commit -m "prompt({category}): promote langfuse v{lf_version} to {name}_v{version}"
  4. 走 PR review（金融审计要求）
  5. merge 后按 ADR 0003 灰度切换（修改 app/prompts/_versions.yaml）

清理：
  - 晋升后 7 天内（ADR 0014 D3）删 LangFuse 上的实验版 prompt，
    避免 staging 数据漂移污染未来实验
"""
    print(msg)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR 0014 D3 · LangFuse → git prompt 晋升工具"
    )
    parser.add_argument(
        "target",
        help="LangFuse prompt 目标，格式 `category.name`，如 swap.intent",
    )
    parser.add_argument(
        "--version",
        type=int,
        default=None,
        help="强制指定输出版本号（默认 = 现有最大版本 + 1）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="目标文件已存在时覆盖（默认拒绝）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不写文件，仅打印目标路径 + 内容前 500 字符",
    )
    args = parser.parse_args()

    category, name = _parse_target(args.target)
    version = args.version if args.version is not None else _next_version(category, name)

    content, lf_version = _fetch_langfuse_prompt(category, name)

    if args.dry_run:
        target = PROMPTS_ROOT / category / f"{name}_v{version}.md"
        print(f"[dry-run] 目标: {target}")
        print(f"[dry-run] LangFuse v{lf_version} 内容前 500 字符:")
        print("-" * 60)
        print(content[:500])
        print("-" * 60)
        print(f"[dry-run] 完整长度 {len(content)} 字符")
        return 0

    target = _write_target(category, name, version, content, force=args.force)
    _print_next_steps(target, category, name, version, lf_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
