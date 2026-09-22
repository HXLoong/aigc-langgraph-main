"""现役 fixture 加载器：三种方言归一化为 GoldenCase（ADR 0024 D6）。

- A 方言（`tests/fixtures/categories/*.jsonl`）：`name/caseNo + send_text + sub_scenes[]`，
  每轮可带独立断言；case 级 `expected` 落到首轮。
- B 方言（`tests/fixtures/unified_golden.jsonl`）：`id + conversation[{raw_content, quote_desc}]`
  + case 级 `expected{product_type, intent, output}`。单轮时 expected 落到首轮；多轮时
  expected 描述的是整段对话中的焦点轮（swap/confirm 是末轮、option/place_from_quote 是中间轮），
  不落到任何一轮，改为 `expected_scope="any_turn"`：任一已执行轮命中即通过。
- raw 方言（`id + raw_content` 单轮，标的回归集）：等价于单轮 A。

一个文件只放一种方言；`categories/` 不接受 B / raw 字段（`scripts/check_fixture_consistency.py`）。
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TurnSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    scene: str = ""
    send_text: str
    at_bot: bool = False
    quote_previous: bool | None = None
    wait_before_seconds: float = Field(default=0, ge=0, le=300)
    #: B 方言的引用说明原文（"用户引用上一条机器人消息"）；首轮标注了引用的上下文依赖 case
    #: 无上一轮回复可引，只能留在这里供概览与人工判读
    quote_desc: str = ""
    expected: dict[str, Any] = Field(default_factory=dict)
    response_contains: list[str] = Field(default_factory=list)
    response_contains_any: list[str] = Field(default_factory=list)
    response_not_contains: list[str] = Field(default_factory=list)


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
    #: 非空即不可执行（如 B 方言某轮 raw_content 为空——用户文本被写进了 quote_desc，Issue #113）；
    #: 加载与计数照常，runner / eval 用 select_runnable 跳过并显式报数
    skip_reason: str = ""
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
        quote_previous=obj.get("quote_previous"),
        wait_before_seconds=obj.get("wait_before_seconds", 0),
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


#: B 方言现役文件（ADR 0024 D6 并入默认发现）
UNIFIED_FIXTURE_NAME = "unified_golden.jsonl"


def discover_fixtures(root: Path = Path("tests/fixtures")) -> list[Path]:
    """现役数据源：categories/*.jsonl（A）+ 根目录 unified_golden.jsonl（B，存在即纳入）。"""
    if root.name == "categories":
        categories, fixtures_root = root, root.parent
    else:
        categories, fixtures_root = root / "categories", root
    paths = sorted(categories.glob("*.jsonl"))
    unified = fixtures_root / UNIFIED_FIXTURE_NAME
    if unified.is_file():
        paths.append(unified)
    return paths


def load_golden(
    paths: Sequence[Path] | Path | None = None,
    *,
    root: Path = Path("tests/fixtures"),
) -> list[GoldenCase]:
    fixture_paths: list[Path]
    if paths is None:
        fixture_paths = discover_fixtures(root)
    else:
        raw_paths = [paths] if isinstance(paths, Path) else list(paths)
        fixture_paths = []
        for path in raw_paths:
            fixture_paths.extend(sorted(path.glob("*.jsonl")) if path.is_dir() else [path])

    cases: list[GoldenCase] = []
    for path in fixture_paths:
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


def validate_case(case: GoldenCase, origin: str = "fixture") -> list[str]:
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


# ── Langfuse Dataset / 本地确定性评分共用的 categories 结构投影 ──


def _dataset_turn_input(turn: TurnSpec) -> dict[str, Any]:
    result: dict[str, Any] = {"send_text": turn.send_text, "at_bot": turn.at_bot}
    if turn.quote_previous is not None:
        result["quote_previous"] = turn.quote_previous
    return result


def _dataset_turn_expected(turn: TurnSpec) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name in (
        "expected",
        "response_contains",
        "response_contains_any",
        "response_not_contains",
    ):
        value = getattr(turn, field_name)
        if value:
            result[field_name] = value
    return result


def dataset_input(case: GoldenCase) -> dict[str, Any]:
    """Dataset Item input：保持 categories 的首轮 + sub_scenes 输入结构。"""
    first, *sub_scenes = case.turns
    return {**_dataset_turn_input(first), "sub_scenes": [_dataset_turn_input(t) for t in sub_scenes]}


def dataset_expected(case: GoldenCase) -> dict[str, Any]:
    """Dataset Item expectedOutput：首轮 + sub_scenes 断言；Code Evaluator（云端与本地）都吃这一份。"""
    first, *sub_scenes = case.turns
    return {**_dataset_turn_expected(first), "sub_scenes": [_dataset_turn_expected(t) for t in sub_scenes]}
