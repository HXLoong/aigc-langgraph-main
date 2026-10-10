"""现役数据集加载器：三种方言归一化为 GoldenCase（ADR 0024 D6）。

- A 方言（`tests/datasets/biz/*.jsonl`）：`name/caseNo + send_text + sub_scenes[]`，
  每轮可带独立断言；case 级 `expected` 落到首轮。
- B 方言（历史 `tests/datasets/unified_golden.jsonl`）：`id + conversation[{raw_content, quote_desc}]`
  + case 级 `expected{product_type, intent, output}`。单轮时 expected 落到首轮；多轮时
  expected 描述的是整段对话中的焦点轮（swap/confirm 是末轮、option/place_from_quote 是中间轮），
  不落到任何一轮，改为 `expected_scope="any_turn"`：任一已执行轮命中即通过。
- raw 方言（`id + raw_content` 单轮，标的回归集）：等价于单轮 A。

一个文件只放一种方言；`biz/` 不接受 B / raw 字段（`scripts/check_dataset_consistency.py`）。
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TurnSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    scene: str = ""
    send_text: str
    at_bot: bool = False
    fast_query: Literal["0", "1"] = "0"
    robot_version: str | None = "V2"
    existing_command: Literal["0", "1"] = "0"
    quote_previous: bool | None = None
    wait_before_seconds: float = Field(default=0, ge=0, le=300)
    #: B 方言的引用说明原文（"用户引用上一条机器人消息"）；首轮标注了引用的上下文依赖 case
    #: 无上一轮回复可引，只能留在这里供概览与人工判读
    quote_desc: str = ""
    #: 意图集冻结上下文（harness/intent_runner.py）：引用文本、历史消息、上一轮产品，
    #: 直接注入 state，不回放上一轮机器人回复；业务集不使用
    quote_content: str = ""
    history: list[dict[str, str]] = Field(default_factory=list)
    prev_product_type: str = ""
    expected: dict[str, Any] = Field(default_factory=dict)
    response_contains: list[str] = Field(default_factory=list)
    response_contains_any: list[str] = Field(default_factory=list)
    response_not_contains: list[str] = Field(default_factory=list)
    #: 多笔卡片块级断言（harness/differ.py::check_block_assertions）：按卡片标题行切块后逐块比对
    response_blocks: list[dict[str, Any]] = Field(default_factory=list)


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    category: str
    type: str = ""
    source: str = ""
    name: str = ""
    case_no: str = ""
    scene: str = ""
    #: a / b / raw，见模块 docstring
    dialect: str = "a"
    #: first_turn：case 级 expected 已复制到 turns[0].expected（A、单轮 B、raw）；
    #: any_turn：多轮 B，case 级 expected 由 differ.check_case_assertions 对所有已执行轮判定
    expected_scope: str = "first_turn"
    #: 非空即不可执行（如 B 方言某轮 raw_content 为空——用户文本被写进了 quote_desc）；
    #: 加载与计数照常，runner / eval 用 select_runnable 跳过并显式报数
    skip_reason: str = ""
    # 固定时段场景的执行前置条件；仅业务回放检查，时区固定为 Asia/Shanghai。
    execution_before: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    turns: list[TurnSpec] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""
    source_path: str = ""
    source_line: int = 0


def _assertion_lines(value: Any, *, origin: str, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ValueError(f"{origin}: {field_name} must be a string or list[str]")


def _block_assertions(value: Any, *, origin: str) -> list[dict[str, Any]]:
    """`response_blocks`：list[object]，块内只认 contains / not_contains（逐块字段断言）。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{origin}: response_blocks must be a list of objects")
    blocks: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{origin}: response_blocks[{index}] must be an object")
        for key in ("contains", "not_contains"):
            if key in item:
                _assertion_lines(item[key], origin=f"{origin}: response_blocks[{index}]", field_name=key)
        blocks.append(item)
    return blocks


def _turn_from_object(
    obj: dict[str, Any], *, origin: str, default_at_bot: bool
) -> TurnSpec:
    send_text = obj.get("send_text")
    if not isinstance(send_text, str) or not send_text.strip():
        raise ValueError(f"{origin}: send_text is required")
    expected = obj.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"{origin}: expected must be an object")
    return TurnSpec(
        scene=str(obj.get("scene") or ""),
        send_text=send_text,
        at_bot=obj.get("at_bot", default_at_bot),
        fast_query=obj.get("fast_query", "0"),
        robot_version=obj.get("robot_version", "V2"),
        existing_command=obj.get("existing_command", "0"),
        quote_previous=obj.get("quote_previous"),
        wait_before_seconds=obj.get("wait_before_seconds", 0),
        quote_content=obj.get("quote_content") or "",
        history=obj.get("history") or [],
        prev_product_type=obj.get("prev_product_type") or "",
        expected=expected,
        response_contains=_assertion_lines(
            obj.get("response_contains"), origin=origin, field_name="response_contains"
        ),
        response_contains_any=_assertion_lines(
            obj.get("response_contains_any"),
            origin=origin,
            field_name="response_contains_any",
        ),
        response_not_contains=_assertion_lines(
            obj.get("response_not_contains"),
            origin=origin,
            field_name="response_not_contains",
        ),
        response_blocks=_block_assertions(obj.get("response_blocks"), origin=origin),
    )


def _detect_dialect(obj: dict[str, Any], *, origin: str) -> str:
    has_a = "send_text" in obj or "sub_scenes" in obj
    has_b = "conversation" in obj
    has_raw = "raw_content" in obj
    if sum((has_a, has_b, has_raw)) > 1:
        raise ValueError(f"{origin}: mixed dialects in one case (send_text / conversation / raw_content)")
    if has_b:
        return "b"
    if has_raw:
        return "raw"
    return "a"


def _b_turns(obj: dict[str, Any], *, origin: str) -> tuple[list[TurnSpec], str]:
    """conversation[] → turns；返回 (turns, skip_reason)。缺 raw_content 键是 schema 错误；
    键在但为空是数据缺陷：不抛，整条 case 标记不可执行。"""
    conversation = obj.get("conversation")
    if not isinstance(conversation, list) or not conversation:
        raise ValueError(f"{origin}: conversation must be a non-empty list")
    turns: list[TurnSpec] = []
    empty_turns: list[int] = []
    for index, turn in enumerate(conversation):
        if not isinstance(turn, dict):
            raise ValueError(f"{origin}: conversation[{index}] must be an object")
        raw_content = turn.get("raw_content")
        if not isinstance(raw_content, str):
            raise ValueError(f"{origin}: conversation[{index}] requires raw_content")
        if not raw_content.strip():
            empty_turns.append(index)
        quote_desc = str(turn.get("quote_desc") or "")
        turns.append(
            TurnSpec(
                scene=f"第 {index + 1} 轮" if index else "",
                send_text=raw_content,
                at_bot=index == 0,
                # 首轮无上一轮回复可引：quote_desc 只记录，不转成 quote_previous
                quote_previous=(True if quote_desc else None) if index else None,
                quote_desc=quote_desc,
            )
        )
    skip_reason = (
        f"conversation{empty_turns} has empty raw_content (user text lives in quote_desc)"
        if empty_turns
        else ""
    )
    return turns, skip_reason


def normalize_case(obj: dict[str, Any], *, origin: str) -> GoldenCase:
    dialect = _detect_dialect(obj, origin=origin)
    case_id = obj.get("id") or obj.get("caseNo")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"{origin}: id or caseNo is required")
    name = str(obj.get("name") or case_id)
    case_no = str(obj.get("caseNo") or case_id)
    origin_path, _, origin_line = origin.rpartition(":")
    category = str(obj.get("category") or Path(origin_path).stem)
    expected = obj.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"{origin}: expected must be an object")

    expected_scope = "first_turn"
    skip_reason = ""
    if dialect == "b":
        turns, skip_reason = _b_turns(obj, origin=origin)
        if len(turns) == 1:
            turns[0].expected = expected
        else:
            expected_scope = "any_turn"
    elif dialect == "raw":
        turns = [_turn_from_object({**obj, "send_text": obj["raw_content"]}, origin=origin, default_at_bot=True)]
    else:
        turns = [_turn_from_object(obj, origin=origin, default_at_bot=True)]
    sub_scenes = obj.get("sub_scenes") or []
    if not isinstance(sub_scenes, list):
        raise ValueError(f"{origin}: sub_scenes must be a list")
    for index, sub_scene in enumerate(sub_scenes):
        if not isinstance(sub_scene, dict):
            raise ValueError(f"{origin}: sub_scenes[{index}] must be an object")
        turns.append(
            _turn_from_object(
                sub_scene,
                origin=f"{origin}:sub_scenes[{index}]",
                default_at_bot=False,
            )
        )

    return GoldenCase(
        id=case_id,
        category=category,
        type=str(obj.get("type") or ""),
        source=str(obj.get("source") or ""),
        name=name,
        case_no=case_no,
        scene=str(obj.get("scene") or ""),
        dialect=dialect,
        expected_scope=expected_scope,
        skip_reason=skip_reason,
        execution_before=obj.get("execution_before"),
        turns=turns,
        expected=expected,
        expected_output=str(expected.get("output") or ""),
        source_path=origin_path,
        source_line=int(origin_line),
    )


def build_overview(case: GoldenCase) -> str:
    """生成 case 概览文本（LangFuse metadata / 本地预览共用）。"""
    expected = case.expected
    lines = [
        f"ID: {case.id}",
        f"类别: {case.category}",
        f"用例类型: {case.type}",
        f"来源: {case.source}",
        f"期望路由: product_type={expected.get('product_type', '')}, intent={expected.get('intent', '')}",
        "对话:",
    ]
    for i, turn in enumerate(case.turns, 1):
        if i > 1 and turn.quote_previous is not False:
            note = "引用上一轮机器人回复"
        elif turn.quote_desc:
            note = f"标注引用（首轮不可回放）: {turn.quote_desc}"
        else:
            note = "无引用"
        lines.append(f"  第{i}轮: send_text={turn.send_text}; {note}")
    return "\n".join(lines)


#: B 方言历史参考集；仅在显式选择时加载（ADR 0030）。
UNIFIED_DATASET_NAME = "unified_golden.jsonl"

#: 现役数据集根与分组目录。种子数据（local_backend/）不是评测用例，不参与发现。
DATASETS_ROOT = Path(__file__).resolve().parents[1] / "tests" / "datasets"
GROUP_DIRS: dict[str, str] = {"biz": "biz", "intent": "intent"}


def group_paths(group: str) -> list[Path]:
    """按数据集分组发现现役 JSONL 文件；`all` 合并 biz 与 intent。"""
    if group not in GROUP_DIRS and group != "all":
        raise ValueError(f"unknown dataset group: {group!r}")
    directories = (
        [DATASETS_ROOT / name for name in GROUP_DIRS.values()]
        if group == "all"
        else [DATASETS_ROOT / GROUP_DIRS[group]]
    )
    return sorted(
        path for directory in directories for path in directory.glob("*.jsonl") if path.is_file()
    )


def file_group(path: Path) -> str:
    """根据文件所在目录判定其数据集分组；不属 biz/intent 即报错。"""
    resolved = path.resolve()
    for group, name in GROUP_DIRS.items():
        if (DATASETS_ROOT / name).resolve() in resolved.parents:
            return group
    raise ValueError(
        f"dataset file must live under tests/datasets/biz or tests/datasets/intent: {path}"
    )


def select_dataset_files(
    group: str | None, files: list[Path] | None
) -> tuple[list[Path], str]:
    """解析 --group 与 --file，返回 (文件列表, 生效分组)。

    显式 --file 时按目录判定分组；未显式指定 --group 时沿用文件分组，
    指定但与文件分组冲突时报错。未指定 --file 时默认加载 biz 分组。
    """
    if files:
        paths: list[Path] = []
        for raw in files:
            if raw.is_dir():
                paths.extend(sorted(p for p in raw.glob("*.jsonl") if p.is_file()))
            else:
                paths.append(raw)
        if not paths:
            raise ValueError("no dataset files selected")
        groups = {file_group(path) for path in paths}
        if group is not None and group != "all" and groups != {group}:
            raise ValueError(f"--group {group!r} conflicts with selected files")
        resolved_group = next(iter(groups)) if len(groups) == 1 else "all"
        return list(dict.fromkeys(paths)), resolved_group
    return group_paths(group or "biz"), group or "biz"


def discover_cases(
    root: Path = Path("tests/datasets"), *, include_unified: bool = False,
) -> list[Path]:
    """默认只读 biz；include_unified 显式纳入同级历史参考集。"""
    if root.name in ("biz", "categories"):
        biz_dir, datasets_root = root, root.parent
    else:
        biz_dir, datasets_root = root / "biz", root
        if not biz_dir.is_dir() and (root / "categories").is_dir():
            biz_dir = root / "categories"  # 旧 checkout 回退
    paths = sorted(biz_dir.glob("*.jsonl"))
    unified = datasets_root / UNIFIED_DATASET_NAME
    if include_unified and unified.is_file():
        paths.append(unified)
    return paths


def load_golden(
    paths: Sequence[Path] | Path | None = None,
    *,
    root: Path = Path("tests/datasets"),
    include_unified: bool = False,
) -> list[GoldenCase]:
    """加载所选文件；include_unified 追加 root 下的参考集，同一路径只追加一次。"""
    case_paths: list[Path]
    if paths is None:
        case_paths = discover_cases(root, include_unified=include_unified)
    else:
        raw_paths = [paths] if isinstance(paths, Path) else list(paths)
        case_paths = []
        for path in raw_paths:
            case_paths.extend(sorted(path.glob("*.jsonl")) if path.is_dir() else [path])
        if include_unified:
            datasets_root = root.parent if root.name in ("biz", "categories") else root
            unified = datasets_root / UNIFIED_DATASET_NAME
            if unified.is_file() and unified.resolve() not in {
                path.resolve() for path in case_paths
            }:
                case_paths.append(unified)

    cases: list[GoldenCase] = []
    for path in case_paths:
        with path.open(encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                origin = f"{path}:{line_number}"
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{origin}: invalid JSON: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ValueError(f"{origin}: case must be an object")
                cases.append(normalize_case(payload, origin=origin))
    return cases


def validate_case(case: GoldenCase, origin: str = "dataset") -> list[str]:
    errors: list[str] = []
    if not case.id.strip():
        errors.append(f"{origin}: id is empty")
    if not case.category.strip():
        errors.append(f"{origin}: category is empty")
    if not case.turns:
        errors.append(f"{origin}: turns is empty")
    return errors


def index_by_category(cases: Iterable[GoldenCase]) -> dict[str, list[GoldenCase]]:
    grouped: dict[str, list[GoldenCase]] = defaultdict(list)
    for case in cases:
        grouped[case.category].append(case)
    return dict(grouped)


def filter_by_category(
    cases: Iterable[GoldenCase], category_prefix: str | None
) -> list[GoldenCase]:
    return [
        case
        for case in cases
        if not category_prefix or case.category.startswith(category_prefix)
    ]


def select_runnable(cases: Iterable[GoldenCase]) -> tuple[list[GoldenCase], list[GoldenCase]]:
    """按 skip_reason 分成 (可执行, 跳过)；调用方必须把跳过数打印出来，不得静默。"""
    runnable: list[GoldenCase] = []
    skipped: list[GoldenCase] = []
    for case in cases:
        (skipped if case.skip_reason else runnable).append(case)
    return runnable, skipped


def filter_by_ids(cases: Iterable[GoldenCase], ids: list[str] | None) -> list[GoldenCase]:
    if not ids:
        return list(cases)
    wanted = set(ids)
    return [case for case in cases if case.id in wanted]


def select_by_ids(cases: Iterable[GoldenCase], ids: list[str] | None) -> list[GoldenCase]:
    """按 ID 精确选择并保持请求顺序；任一 ID 未命中即报错，不静默漏跑。"""
    selected = list(cases)
    if not ids:
        return selected
    wanted = list(dict.fromkeys(ids))
    by_id = {case.id: case for case in selected}
    missing = [case_id for case_id in wanted if case_id not in by_id]
    if missing:
        raise ValueError(f"未找到用例 ID：{', '.join(missing)}")
    return [by_id[case_id] for case_id in wanted]


# ── Langfuse Dataset / 本地确定性评分共用的 biz 结构投影 ──


def _dataset_turn_input(turn: TurnSpec) -> dict[str, Any]:
    result: dict[str, Any] = {
        "send_text": turn.send_text, "at_bot": turn.at_bot,
        "robot_version": turn.robot_version, "existing_command": turn.existing_command,
    }
    if turn.fast_query != "0":
        result["fast_query"] = turn.fast_query
    if turn.quote_previous is not None:
        result["quote_previous"] = turn.quote_previous
    if turn.wait_before_seconds:
        result["wait_before_seconds"] = turn.wait_before_seconds
    for field_name in ("quote_content", "history", "prev_product_type"):
        value = getattr(turn, field_name)
        if value:
            result[field_name] = value
    return result


def _dataset_turn_expected(turn: TurnSpec) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name in (
        "expected",
        "response_contains",
        "response_contains_any",
        "response_not_contains",
        "response_blocks",
    ):
        value = getattr(turn, field_name)
        if value:
            result[field_name] = value
    return result


def dataset_input(case: GoldenCase) -> dict[str, Any]:
    """Dataset Item input：保持 biz 的首轮 + sub_scenes 输入结构。"""
    first, *sub_scenes = case.turns
    result = {**_dataset_turn_input(first), "sub_scenes": [_dataset_turn_input(t) for t in sub_scenes]}
    if case.execution_before:
        result["execution_before"] = case.execution_before
    return result


def dataset_expected(case: GoldenCase) -> dict[str, Any]:
    """Dataset Item expectedOutput：首轮 + sub_scenes 断言；Code Evaluator（云端与本地）都吃这一份。"""
    first, *sub_scenes = case.turns
    return {**_dataset_turn_expected(first), "sub_scenes": [_dataset_turn_expected(t) for t in sub_scenes]}
