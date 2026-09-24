#!/usr/bin/env python3
"""推送提示词到 Langfuse（单向：git → Langfuse，不拉回）。

无 [user] 段补一条 chat user 消息（UI Prompt Experiment 只支持单轮，要求 prompt 变量名与
dataset item 键同名）；system 段一字不改。它不跑 LangGraph 图，链路回归用 langfuse_eval.py。

真源永远是 git 的 .md；批量同步读取 staging 仅用于跳过未变内容。

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
    python scripts/langfuse/upload_prompt_to_langfuse.py --sync-all --dry-run
    python scripts/langfuse/upload_prompt_to_langfuse.py --sync-all

退出码：
    0 成功
    1 目标不存在 / 内容无效
    2 配置缺失 / 网络问题
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from app.prompts import _langfuse_name, _parse_prompt_md  # noqa: E402
from scripts.langfuse._public_api import (  # noqa: E402
    load_dotenv,
    missing_langfuse_config,
    resolve_base_url,
)

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

SYNC_CATEGORIES = ("option", "option_close", "swap")


@dataclass(frozen=True)
class SyncPrompt:
    name: str
    path: Path
    body: list[dict[str, str]]


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


def _build_prompt_body(
    system: str, user_template: str, experiment: bool
) -> tuple[str, str | list[dict[str, str]], str]:
    """决定上传类型与内容，返回 (prompt 类型, 内容, user 来源说明)。

    - `.md` 自带 [user] 段 → chat，用 git 的 user 模板（实验与演练一致，无需替换）
    - 无 [user] 段 + experiment → chat，user 用 EXPERIMENT_USER_TEMPLATE
    - 无 [user] 段 + --plain → text，纯 system（UI experiment 会报 no variables）

    system 段始终是 git 原文。与 app/prompts/__init__.py::_load_from_langfuse 的
    反序列化契约（list → 按 role 取 system / user）一一对应。
    """
    if user_template:
        return (
            "chat",
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_template},
            ],
            "git 的 [user] 段",
        )
    if experiment:
        return (
            "chat",
            [
                {"role": "system", "content": system},
                {"role": "user", "content": EXPERIMENT_USER_TEMPLATE},
            ],
            "实验用 user 模板（source_payload 首轮形状）",
        )
    return "text", system, "纯 system（无 user 段）"


def _collect_sync_prompts(root: Path) -> list[SyncPrompt]:
    """扫描三个业务目录并在任何远端写入之前校验所有内容与名称。"""
    prompts: list[SyncPrompt] = []
    names: dict[str, Path] = {}
    for category in SYNC_CATEGORIES:
        for path in sorted((root / category).glob("*.md")):
            source = path.read_text(encoding="utf-8")
            system, user = _parse_prompt_md(source)
            if not system:
                raise ValueError(f"{path} 未找到 [system] 段或内容为空")
            if re.search(r"^##\s*\[user\]", source, flags=re.MULTILINE) and not user:
                raise ValueError(f"{path} 的 [user] 段无法解析或内容为空")
            name = _langfuse_name(category, path.stem)
            if name in names:
                raise ValueError(f"Langfuse 名称冲突 {name}: {names[name]} 与 {path}")
            names[name] = path
            prompt_type, body, _ = _build_prompt_body(system, user, experiment=True)
            if prompt_type != "chat" or not isinstance(body, list):
                raise ValueError(f"{path} 无法生成 chat Prompt")
            prompts.append(SyncPrompt(name=name, path=path, body=body))
    if not prompts:
        raise ValueError(f"{root} 下未找到可同步的提示词")
    return prompts


def _remote_type(remote: Any) -> str:
    """SDK PromptClient 没有统一的 type 属性，由 prompt 形态判断。"""
    if isinstance(remote.prompt, list):
        return "chat"
    if isinstance(remote.prompt, str):
        return "text"
    raise ValueError(f"Langfuse 返回了未知 Prompt 内容类型: {type(remote.prompt).__name__}")


def _comparable_chat_body(body: list[Any]) -> list[Any]:
    """SDK 4.15.0 在 chat 消息上补 type=message；比较时去掉这一层包装。"""
    return [
        {"role": msg["role"], "content": msg["content"]}
        if isinstance(msg, dict)
        and set(msg) == {"type", "role", "content"}
        and msg["type"] == "message"
        else msg
        for msg in body
    ]


def _sync_prompt(lf: Any, prompt: SyncPrompt) -> str:
    """用无缓存的 staging 版本做内容比较；只有明确的 404 才视作缺失。"""
    from langfuse.api.commons.errors.not_found_error import NotFoundError

    try:
        existing = lf.get_prompt(prompt.name, label=DEFAULT_LABEL, cache_ttl_seconds=0)
    except NotFoundError:
        # staging 缺失时还要检查同名最新版本的类型；Langfuse 不允许跨类型建新版。
        try:
            existing = lf.get_prompt(prompt.name, label="latest", cache_ttl_seconds=0)
        except NotFoundError:
            existing = None
        if existing is not None and _remote_type(existing) != "chat":
            raise ValueError(
                f"{prompt.name} type 冲突：远端为 {_remote_type(existing)}，Git 为 chat"
            ) from None
        action = "created" if existing is None else "updated"
    else:
        if _remote_type(existing) != "chat":
            raise ValueError(
                f"{prompt.name} type 冲突：远端为 {_remote_type(existing)}，Git 为 chat"
            )
        if _comparable_chat_body(existing.prompt) == prompt.body:
            return "skipped"
        action = "updated"

    lf.create_prompt(name=prompt.name, type="chat", prompt=prompt.body, labels=[DEFAULT_LABEL])
    return action


def _sync_all(lf: Any, root: Path) -> dict[str, int]:
    prompts = _collect_sync_prompts(root)
    counts = {"created": 0, "updated": 0, "skipped": 0}
    for prompt in prompts:
        action = _sync_prompt(lf, prompt)
        counts[action] += 1
        print(f"{action}: {prompt.name} ({prompt.path})")
    return counts


def _new_client(base_url: str | None):
    from langfuse import Langfuse

    return Langfuse(base_url=base_url)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR 0014 D3 · git 提示词 → Langfuse 演练区（单向推送）"
    )
    parser.add_argument("target", nargs="?", help="格式 `category.name`，如 option_close.intent")
    parser.add_argument(
        "--sync-all", action="store_true", help="同步三个业务目录的顶层 .md 到 staging"
    )
    parser.add_argument("--base-url", help="覆盖 LANGFUSE_BASE_URL / LANGFUSE_HOST")
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

    if args.sync_all:
        if args.target or args.plain or args.label != DEFAULT_LABEL:
            parser.error("--sync-all 不能与 target、--plain 或非 staging 的 --label 同用")
        try:
            prompts = _collect_sync_prompts(PROMPTS_ROOT)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"已校验 {len(prompts)} 个提示词，目标标签 [{DEFAULT_LABEL}]")
        if args.dry_run:
            for prompt in prompts:
                print(f"[dry-run] {prompt.name}: {prompt.path}")
            return 0
    elif not args.target:
        parser.error("需要 target 或 --sync-all")

    if not args.sync_all:
        category, name = _parse_target(args.target)
        system, user_template, path = _read_workspace_prompt(category, name)
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

    base_url = resolve_base_url(args.base_url)
    missing = missing_langfuse_config(base_url, require_base_url=args.sync_all)
    if missing:
        print(f"ERROR: 缺少配置: {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        lf = _new_client(base_url)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Langfuse 客户端初始化失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.sync_all:
        try:
            counts = _sync_all(lf, PROMPTS_ROOT)
        except ValueError as exc:
            print(f"ERROR: 批量同步失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: 批量同步失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(
            f"同步完成：新建 {counts['created']}，更新 {counts['updated']}，跳过 {counts['skipped']}"
        )
        return 0

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
