#!/usr/bin/env python3
"""Validate the active datasets under tests/datasets/: biz/*.jsonl (A dialect)
+ unified_golden.jsonl (B dialect) + intent/*.jsonl (意图集，A 方言子集).

ADR 0024 D6：现役数据源同受 lint；一个文件只放一种方言，id 跨文件唯一。
意图集（tests/datasets/intent/）只评路由与意图：逐轮必须标 expected.product_type / intent
且取运行时枚举值，禁止出现卡片文本断言（那是 biz/ 业务集的职责）。

另有两组可判定规则（只看结构与显式声明，不猜测语义）：
- 写类用例的结构化期望：有 expected 却缺 place_params / close_params 逐条告警；整份文件完全没有
  结构化期望时按文件汇总一条告警（互换 3 个文件属后者）。
- 意图集的 reference 结构，以及派生 source 的可解析性与所指 biz 用例的存在性。占位数据待补的文件列在
  PENDING_LINT_WAIVERS，降级为告警，使 lint 在补数据前保持通过。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Keep the documented `python scripts/check_dataset_consistency.py` entry point usable.
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from harness.intent_context import has_frozen_context, requires_replay  # noqa: E402
from harness.references import validate_expected_references  # noqa: E402

UNIFIED_DATASET_NAME = "unified_golden.jsonl"
#: 运行时 product_type 取值（app/graph/state.py ProductType）；数据集标了别的值只告警不阻断
KNOWN_PRODUCT_TYPES = ("swap", "option", "option_close", "unknown")
#: 意图集目录（与 biz/ 平级）；文件按产品命名，id 以 intent- 开头
BUSINESS_DIR_NAME = "biz"
LEGACY_BUSINESS_DIR_NAME = "categories"
INTENT_DIR_NAME = "intent"
INTENT_ID_PREFIX = "intent-"
INTENT_CASE_TYPES = ("positive", "negative")
INTENT_PRODUCTS = ("swap", "option", "option_close")
TEXT_ASSERTION_FIELDS = (
    "response_contains", "response_contains_any", "response_not_contains", "response_blocks",
)


def intent_types_by_product() -> dict[str, tuple[str, ...]]:
    """运行时意图枚举（唯一真源是各子图 models.py 的 Literal，不在此复制）。"""
    from typing import get_args

    from app.subgraphs.close.models import CloseIntentType
    from app.subgraphs.option.models import OptionIntentType
    from app.subgraphs.swap.models import SwapIntentType

    return {
        "swap": tuple(get_args(SwapIntentType)),
        "option": tuple(get_args(OptionIntentType)),
        "option_close": tuple(get_args(CloseIntentType)),
        # 一级路由落 unknown 时不进子图，运行时 intent 为空：反案例不标 intent
        "unknown": (),
    }


def swap_transaction_types() -> tuple[str, ...]:
    """标的识别用例 transaction_type 的合法取值（swap 订单项 placeOrderTransactionType）。"""
    from typing import get_args

    from app.subgraphs.swap.models import SwapTransactionType

    return tuple(get_args(SwapTransactionType))


def _check_instruments(origin: str, product_type: str, instruments: Any) -> list[str]:
    """expected.instruments：标的识别断言，只支持 swap；expression 任一候选，transaction_type 可选。"""
    if product_type != "swap":
        return [f"{origin}: expected.instruments is only supported for product_type 'swap'"]
    if not isinstance(instruments, list) or not instruments:
        return [f"{origin}: expected.instruments must be a non-empty list"]
    errors: list[str] = []
    markets = swap_transaction_types()
    for index, item in enumerate(instruments):
        label = f"{origin}: instruments[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        expressions = _lines(item.get("expression"))
        if not expressions:
            errors.append(f"{label}.expression must be a non-empty string or list[str]")
        if "transaction_type" in item:
            candidates = _lines(item["transaction_type"])
            if not candidates:
                errors.append(f"{label}.transaction_type must be a non-empty string or list[str]")
            for candidate in candidates or []:
                if candidate not in markets:
                    errors.append(
                        f"{label}.transaction_type {candidate!r} is not a SwapTransactionType {markets}"
                    )
    return errors


def _lines(value: Any) -> list[str] | None:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    return None


def _iter_jsonl(path: Path, errors: list[str]):
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        errors.append(f"{path}: empty file")
        return
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        origin = f"{path}:{line_number}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{origin}: invalid JSON: {exc}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{origin}: case must be an object")
            continue
        yield origin, obj


#: 写类 category（下单 / 确认 / 询价建单 / 平仓）：ADR 0024 D6 要求 positive case 带
#: `expected.place_params` / `close_params`（从真实 HTTP payload 反向生成后人工抽检），
#: 否则评估门只靠文案。现阶段缺失记 WARNING；业务方补齐后升为 ERROR。
#: 历史名（旧方言 / B 方言 / 单测用）；现役 biz/ 用 LIVE_WRITE_CATEGORIES 的取值。
WRITE_CATEGORIES = frozenset({
    "swap/place_order", "swap/modify", "swap/confirm", "swap/confirm_modify",
    "option/place_order", "option/place_from_quote", "option/inquiry", "option/inquiry_place",
    "option/confirm", "option/modify_request",
    "option_close/place", "option_close/place_amend", "option_close/confirm",
})
#: 现役 biz/*.jsonl 实际使用的 category 值（一个文件一个值），全部属写类链路。
LIVE_WRITE_CATEGORIES = frozenset({
    "swap_prod_data",
    "swap_prod_acceptance_data",
    "swap_test_fuzzy_target_recog_data",
    "option_inquiry_case",
    "option_open_case",
    "option_close_case",
})
WRITE_CATEGORY_SET = WRITE_CATEGORIES | LIVE_WRITE_CATEGORIES
#: 结构化写参数字段：互换/期权下单用 place_params，平仓用 close_params（harness 侧同名）
_PARAM_KEYS = ("place_params", "close_params")
_ORDER_LIST_KEYS = ("orderList", "closeOrderList")

#: 意图集 reference 允许的键（scripts/derive_instrument_fixtures.py 产出）
_REFERENCE_KEYS = frozenset({"backend_codes", "original_instrument_assertions"})
#: 证券代码形态：<code>.<市场后缀>，如 300748.SZ / 0700.HK / YMM.N / COHX.BAT / A21007.SH
_SECURITY_CODE_RE = re.compile(r"^[A-Z0-9]{1,8}\.[A-Z]{1,3}$")
#: 金额下单用例的币种标记（与标的代码同列，见 reference.backend_codes）
_CURRENCY_CODES = frozenset({"CNY", "HKD", "USD", "JPY", "EUR"})
#: 意图集派生来源：derived:<biz category>#<biz caseNo>
_SOURCE_RE = re.compile(r"^derived:(?P<namespace>[A-Za-z0-9_]+)#(?P<case_no>[^\s#]+)$")
#: 已知待补数据文件 → 豁免理由；命中时相关项降级为告警。条目消掉即恢复严格校验。
PENDING_LINT_WAIVERS: dict[str, str] = {
    "swap_instrument.jsonl": "未能自助下单的标的在 backend_codes 留 【待补充】占位（derive_instrument_fixtures 兜底），待业务补码",
}


def is_write_category(value: str) -> bool:
    """写类类目判定（历史名 + 现役名）。"""
    return value in WRITE_CATEGORY_SET


def _case_id(obj: dict[str, Any]) -> Any:
    """A 方言用 caseNo，B 方言用 id。"""
    return obj.get("id") or obj.get("caseNo")


def _lint_place_params(origin: str, obj: dict[str, Any], expected: dict[str, Any],
                       errors: list[str], warnings: list[str]) -> None:
    case_id = _case_id(obj)
    declared = [key for key in _PARAM_KEYS if key in expected]
    if declared:
        for key in declared:
            params = expected[key]
            order_list = params.get("orderList", params.get("closeOrderList")) if isinstance(params, dict) else None
            if not isinstance(params, dict) or not isinstance(order_list, list):
                errors.append(
                    f"{origin}: {case_id!r} expected.{key} must be an object with {'/'.join(_ORDER_LIST_KEYS)} list"
                )
        return
    if is_write_category(str(obj.get("category") or "")) and obj.get("type", "positive") == "positive":
        warnings.append(
            f"{origin}: {case_id!r} write-class case {obj.get('category')!r} has no expected.place_params"
            " (ADR 0024 D6; evaluation gate falls back to text only)"
        )


def _lint_block_assertions(origin: str, obj: dict[str, Any], errors: list[str]) -> None:
    """`response_blocks`：非空 list[object]，块内只认 contains / not_contains。"""
    blocks = obj.get("response_blocks")
    if blocks is None:
        return
    if not isinstance(blocks, list) or not blocks:
        errors.append(f"{origin}: response_blocks must be a non-empty list of objects")
        return
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"{origin}: response_blocks[{index}] must be an object")
            continue
        unknown = sorted(set(block) - {"contains", "not_contains"})
        if unknown:
            errors.append(f"{origin}: response_blocks[{index}] has unknown keys {unknown}")
        for key in ("contains", "not_contains"):
            if key in block and _lines(block[key]) is None:
                errors.append(f"{origin}: response_blocks[{index}].{key} must be string or list[str]")


def _is_security_code(code: object) -> bool:
    """标的代码或金额下单的币种标记；占位符不算。"""
    return isinstance(code, str) and (
        code in _CURRENCY_CODES or _SECURITY_CODE_RE.match(code) is not None
    )


def _lint_reference(origin: str, obj: dict[str, Any], errors: list[str], warnings: list[str],
                    *, waived_reason: str | None) -> None:
    """意图集 reference：结构、证券码形态、未知键（派生标的来源，不上送后端）。"""
    reference = obj.get("reference")
    if reference is None:
        return
    sink = warnings if waived_reason else errors
    prefix = f"{origin}: " if not waived_reason else f"{origin}: pending waiver ({waived_reason}): "

    def add(problem: str) -> None:
        sink.append(prefix + problem)

    if not isinstance(reference, dict):
        add("reference must be an object")
        return
    unknown = sorted(set(reference) - _REFERENCE_KEYS)
    if unknown:
        add(f"reference has unknown keys {unknown}")
    codes = reference.get("backend_codes")
    if not isinstance(codes, list) or not codes:
        add("reference.backend_codes must be a non-empty list[str]")
    else:
        for index, code in enumerate(codes):
            if not _is_security_code(code):
                add(
                    f"reference.backend_codes[{index}] {code!r} is not a security code or currency"
                    " (placeholder not allowed)"
                )
    assertions = reference.get("original_instrument_assertions")
    if assertions is None:
        return
    if not isinstance(assertions, list):
        add("reference.original_instrument_assertions must be a list")
        return
    for index, item in enumerate(assertions):
        expressions = item.get("expression") if isinstance(item, dict) else None
        if not _lines(expressions):
            add(
                f"reference.original_instrument_assertions[{index}].expression"
                " must be a non-empty string or list[str]"
            )


def _lint_derived_source(origin: str, obj: dict[str, Any], biz_index: dict[str, dict[str, Any]],
                         errors: list[str], warnings: list[str]) -> None:
    """派生 source：命名空间 / 编号可解析，且指向的 biz 用例真实存在。"""
    source = obj.get("source")
    if not isinstance(source, str) or not source.startswith("derived:"):
        return
    match = _SOURCE_RE.match(source.strip())
    if match is None:
        errors.append(f"{origin}: source {source!r} must be 'derived:<namespace>#<caseNo>'")
        return
    case_no = match.group("case_no")
    biz_case = biz_index.get(case_no)
    if biz_case is None:
        errors.append(f"{origin}: source references unknown biz case {case_no!r}")
        return
    category = str(biz_case.get("category") or "")
    namespace = match.group("namespace")
    if namespace != category:
        warnings.append(
            f"{origin}: source namespace {namespace!r} differs from biz category {category!r} (legacy namespace)"
        )


def validate_unified(path: Path, ids: list[str]) -> tuple[list[str], list[str]]:
    """B 方言 lint：id + conversation[].raw_content + expected{product_type, intent}；返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    for origin, obj in _iter_jsonl(path, errors):
        a_fields = sorted(key for key in ("send_text", "sub_scenes", "name") if key in obj)
        if a_fields:
            errors.append(f"{origin}: fields {a_fields} belong to the A dialect (biz/), not {path.name}")
        case_id = obj.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"{origin}: missing id")
        else:
            ids.append(case_id)
        if not isinstance(obj.get("category"), str) or not obj["category"].strip():
            errors.append(f"{origin}: missing category")
        conversation = obj.get("conversation")
        if not isinstance(conversation, list) or not conversation:
            errors.append(f"{origin}: conversation must be a non-empty list")
        else:
            for index, turn in enumerate(conversation):
                if not isinstance(turn, dict) or not isinstance(turn.get("raw_content"), str):
                    errors.append(f"{origin}: conversation[{index}] missing raw_content")
                elif not turn["raw_content"].strip():
                    warnings.append(
                        f"{origin}: {obj.get('id')!r} conversation[{index}] raw_content is empty"
                        " (unrunnable, harness skips it; 业务方 review)"
                    )
        expected = obj.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{origin}: expected must be an object")
            continue
        for field_name in ("product_type", "intent"):
            if not isinstance(expected.get(field_name), str) or not expected[field_name].strip():
                errors.append(f"{origin}: expected.{field_name} is required")
        _lint_place_params(origin, obj, expected, errors, warnings)
        product_type = expected.get("product_type")
        if isinstance(product_type, str) and product_type not in KNOWN_PRODUCT_TYPES:
            warnings.append(
                f"{origin}: {case_id!r} expected.product_type={product_type!r} is not a runtime ProductType"
                f" {KNOWN_PRODUCT_TYPES} (业务方 review)"
            )
    return errors, warnings


#: 冻结历史消息允许的角色（app.graph.state.Message.role）
HISTORY_ROLES = ("user", "assistant", "system")
#: prev_product_type 只能是会进子图的产品（intent_route 多轮粘性只继承这三类）
STICKY_PRODUCT_TYPES = ("swap", "option", "option_close")


def _check_intent_context(origin: str, turn: dict[str, Any]) -> list[str]:
    """意图集冻结上下文字段格式（引用 / 历史 / 上一轮产品写死在数据集用例，见 harness/intent_context.py）。"""
    errors: list[str] = []
    if "quote_content" in turn and (
        not isinstance(turn["quote_content"], str) or not turn["quote_content"].strip()
    ):
        errors.append(f"{origin}: quote_content must be a non-empty string")
    history = turn.get("history", [])
    if not isinstance(history, list):
        errors.append(f"{origin}: history must be a list of {{role, content}}")
        history = []
    for index, message in enumerate(history):
        if not isinstance(message, dict):
            errors.append(f"{origin}: history[{index}] must be an object {{role, content}}")
            continue
        if message.get("role") not in HISTORY_ROLES:
            errors.append(f"{origin}: history[{index}].role must be one of {HISTORY_ROLES}: {message.get('role')!r}")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{origin}: history[{index}].content must be a non-empty string")
    if "prev_product_type" in turn and turn["prev_product_type"] not in STICKY_PRODUCT_TYPES:
        errors.append(
            f"{origin}: prev_product_type must be one of {STICKY_PRODUCT_TYPES}: {turn['prev_product_type']!r}"
        )
    return errors


def _check_intent_turn(origin: str, turn: dict[str, Any], intents: dict[str, tuple[str, ...]]) -> list[str]:
    """一轮意图集断言：只允许 expected.product_type / intent，值取运行时枚举；上下文须冻结。"""
    errors: list[str] = _check_intent_context(origin, turn)
    for field_name in TEXT_ASSERTION_FIELDS:
        if field_name in turn:
            errors.append(
                f"{origin}: {field_name} belongs to the business suite (biz/), not {INTENT_DIR_NAME}/"
            )
    expected = turn.get("expected")
    if not isinstance(expected, dict):
        errors.append(f"{origin}: expected.product_type is required")
        errors.append(f"{origin}: expected.intent is required")
        return errors
    product_type = expected.get("product_type")
    if not isinstance(product_type, str) or not product_type.strip():
        errors.append(f"{origin}: expected.product_type is required")
        return errors
    if product_type not in intents:
        errors.append(
            f"{origin}: product_type {product_type!r} is not a runtime ProductType {KNOWN_PRODUCT_TYPES}"
        )
        return errors
    intent = expected.get("intent")
    if product_type == "unknown":
        if intent is not None:
            errors.append(f"{origin}: product_type 'unknown' has no subgraph intent; drop expected.intent")
        return errors
    if not isinstance(intent, str) or not intent.strip():
        errors.append(f"{origin}: expected.intent is required")
    elif intent not in intents[product_type]:
        errors.append(
            f"{origin}: intent {intent!r} is not a {product_type} intent {intents[product_type]}"
        )
    if "instruments" in expected:
        errors.extend(_check_instruments(origin, product_type, expected["instruments"]))
    return errors


def validate_intent(path: Path, ids: list[str], *, biz_index: dict[str, dict[str, Any]] | None = None,
                    warnings: list[str] | None = None) -> list[str]:
    """意图集 lint：A 方言子集 + 逐轮 expected + 命名约定 + reference / 派生 source；返回 errors。"""
    errors: list[str] = []
    warnings = warnings if warnings is not None else []
    biz_index = biz_index or {}
    waived_reason = PENDING_LINT_WAIVERS.get(path.name)
    intents = intent_types_by_product()
    for origin, obj in _iter_jsonl(path, errors):
        b_fields = sorted(key for key in ("conversation", "raw_content") if key in obj)
        if b_fields:
            errors.append(f"{origin}: fields {b_fields} belong to the B dialect, not {INTENT_DIR_NAME}/")
        case_id = obj.get("id") or obj.get("caseNo")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"{origin}: missing id/caseNo")
        else:
            ids.append(case_id)
            if not case_id.startswith(INTENT_ID_PREFIX):
                errors.append(f"{origin}: id must start with {INTENT_ID_PREFIX!r}: {case_id!r}")
        if not isinstance(obj.get("name", obj.get("caseNo")), str):
            errors.append(f"{origin}: missing name/caseNo")
        category = obj.get("category")
        if not isinstance(category, str) or category not in {
            f"{INTENT_DIR_NAME}/{product}" for product in INTENT_PRODUCTS
        }:
            errors.append(
                f"{origin}: category must be '{INTENT_DIR_NAME}/<product>' with product in {INTENT_PRODUCTS}: {category!r}"
            )
        if obj.get("type") not in INTENT_CASE_TYPES:
            errors.append(f"{origin}: type must be positive or negative: {obj.get('type')!r}")
        if not isinstance(obj.get("send_text"), str) or not obj["send_text"].strip():
            errors.append(f"{origin}: missing send_text")
        errors.extend(_check_intent_turn(origin, obj, intents))
        _lint_reference(origin, obj, errors, warnings, waived_reason=waived_reason)
        _lint_derived_source(origin, obj, biz_index, errors, warnings)
        sub_scenes = obj.get("sub_scenes", [])
        if not isinstance(sub_scenes, list):
            errors.append(f"{origin}: sub_scenes must be a list")
            continue
        for index, sub_scene in enumerate(sub_scenes):
            sub_origin = f"{origin}: sub_scenes[{index}]"
            if not isinstance(sub_scene, dict):
                errors.append(f"{sub_origin} must be an object")
                continue
            if not isinstance(sub_scene.get("send_text"), str) or not sub_scene["send_text"].strip():
                errors.append(f"{sub_origin} missing send_text")
            errors.extend(_check_intent_turn(sub_origin, sub_scene, intents))
        turns = [obj, *(scene for scene in sub_scenes if isinstance(scene, dict))]
        if has_frozen_context(turns) and requires_replay(turns):
            errors.append(
                f"{origin}: case mixes frozen context (quote_content/history/prev_product_type) with replay "
                "(quote_previous or {{previous_*}}); frozen fields are ignored when replaying — freeze every turn"
            )
    return errors


def _datasets_root(root: Path) -> Path:
    return root.parent if root.name in (BUSINESS_DIR_NAME, LEGACY_BUSINESS_DIR_NAME) else root


def _business_dir(root: Path) -> Path:
    if root.name in (BUSINESS_DIR_NAME, LEGACY_BUSINESS_DIR_NAME):
        return root
    biz = root / BUSINESS_DIR_NAME
    return biz if biz.is_dir() else root / LEGACY_BUSINESS_DIR_NAME


def _intent_paths(root: Path) -> list[Path]:
    datasets_root = _datasets_root(root)
    intent_dir = datasets_root / INTENT_DIR_NAME
    return sorted(intent_dir.glob("*.jsonl")) if intent_dir.is_dir() else []


def _unified_path(root: Path) -> Path:
    datasets_root = _datasets_root(root)
    return datasets_root / UNIFIED_DATASET_NAME


def collect_warnings(root: Path) -> list[str]:
    """现役 biz + intent + unified 的全部告警（B 方言在前，保持既有索引语义）。"""
    warnings: list[str] = []
    validate(root, warnings_out=warnings)
    return warnings


def validate(root: Path, verbose: bool = False, *,
             warnings_out: list[str] | None = None) -> list[str]:
    business_dir = _business_dir(root)
    if not business_dir.is_dir():
        return [f"missing dataset directory: {business_dir}"]
    paths = sorted(business_dir.glob("*.jsonl"))
    if not paths:
        return [f"no JSONL cases found: {business_dir}"]

    errors: list[str] = []
    warnings: list[str] = []
    ids: list[str] = []
    biz_index: dict[str, dict[str, Any]] = {}
    without_structured: dict[str, int] = {}
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            errors.append(f"{path}: empty file")
            continue
        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            origin = f"{path}:{line_number}"
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{origin}: invalid JSON: {exc}")
                continue
            if not isinstance(obj, dict):
                errors.append(f"{origin}: case must be an object")
                continue
            b_fields = sorted(key for key in ("conversation", "raw_content") if key in obj)
            if b_fields:
                errors.append(
                    f"{origin}: fields {b_fields} belong to the B dialect ({UNIFIED_DATASET_NAME}), not {BUSINESS_DIR_NAME}/"
                )
            case_id = _case_id(obj)
            errors.extend(f"{origin}: {error}" for error in validate_expected_references(obj.get("expected")))
            if not isinstance(case_id, str) or not case_id.strip():
                errors.append(f"{origin}: missing id/caseNo")
            else:
                ids.append(case_id)
                biz_index.setdefault(case_id, obj)
            expected = obj.get("expected")
            if isinstance(expected, dict):
                _lint_place_params(origin, obj, expected, errors, warnings)
            elif is_write_category(str(obj.get("category") or path.stem)):
                without_structured[path.name] = without_structured.get(path.name, 0) + 1
            if not isinstance(obj.get("name", obj.get("caseNo")), str):
                errors.append(f"{origin}: missing name/caseNo")
            if not isinstance(obj.get("send_text"), str) or not obj["send_text"].strip():
                errors.append(f"{origin}: missing send_text")
            category = str(obj.get("category") or path.stem)
            if not category.startswith(("swap", "option", "option_close")):
                errors.append(f"{origin}: invalid category {category!r}")
            for field_name in ("response_contains", "response_contains_any", "response_not_contains"):
                if field_name in obj and _lines(obj[field_name]) is None:
                    errors.append(f"{origin}: {field_name} must be string or list[str]")
            _lint_block_assertions(origin, obj, errors)
            sub_scenes = obj.get("sub_scenes", [])
            if not isinstance(sub_scenes, list):
                errors.append(f"{origin}: sub_scenes must be a list")
            else:
                for index, sub_scene in enumerate(sub_scenes):
                    if not isinstance(sub_scene, dict) or not isinstance(sub_scene.get("send_text"), str) or not sub_scene["send_text"].strip():
                        errors.append(f"{origin}: sub_scenes[{index}] missing send_text")
                    if isinstance(sub_scene, dict):
                        _lint_block_assertions(f"{origin}: sub_scenes[{index}]", sub_scene, errors)
                        errors.extend(
                            f"{origin}: {error}" for error in validate_expected_references(
                                sub_scene.get("expected"), f"sub_scenes[{index}].expected",
                            )
                        )
    for filename, count in sorted(without_structured.items()):
        warnings.append(
            f"{filename}: {count} write-class case(s) have no structured expected"
            " (ADR 0024 D6; evaluation gate falls back to text only)"
        )
    for intent_path in _intent_paths(root):
        errors.extend(validate_intent(intent_path, ids, biz_index=biz_index, warnings=warnings))
        paths.append(intent_path)
    unified = _unified_path(root)
    if unified.is_file():
        unified_errors, unified_warnings = validate_unified(unified, ids)
        errors.extend(unified_errors)
        warnings = [*unified_warnings, *warnings]
        paths.append(unified)
    for duplicate, count in Counter(ids).items():
        if count > 1:
            errors.append(f"duplicate id {duplicate!r}: {count} occurrences")
    if verbose:
        print(f"validated {len(paths)} dataset files and {len(ids)} cases")
    if warnings_out is not None:
        warnings_out.extend(warnings)
        missing_params = sum("expected.place_params" in warning for warning in warnings)
        if missing_params:
            print(f"write-class cases without expected.place_params: {missing_params} (ADR 0024 D6)")
        for warning in warnings:
            print(f"WARNING: {warning}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "tests" / "datasets")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    errors = validate(args.root, args.verbose)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2 if any(error.startswith("missing dataset") or error.startswith("no JSONL") for error in errors) else 1
    print("dataset consistency: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
