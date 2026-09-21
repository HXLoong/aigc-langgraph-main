"""拆分完整执行短语候选，保留证据，再交给既有校验处理否定、冲突及数值。"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

_POV = re.compile(r"(?P<mode>POV)\s*(?P<ratio>[0-9]+(?:\.[0-9]+)?)\s*[%％]?", re.I)
_TWAP_DURATION = re.compile(r"(?P<mode>TWAP)\s*[0-9]+(?:\.[0-9]+)?\s*(?:分钟|分|小时|min(?:utes)?)", re.I)
_TWAP_RANGE = re.compile(
    r"(?P<mode>TWAP)\s*(?P<start>[0-9]{1,2}[:：][0-9]{1,2})"
    r"\s*[-－–~～至到]\s*(?P<end>[0-9]{1,2}[:：][0-9]{1,2})", re.I,
)


def split_execution_fragments(candidates: BaseModel) -> BaseModel:
    """仅拆分完整匹配的原文，不改 evidence/origin，不覆盖显式独立参数。"""
    payload = candidates.model_dump(by_alias=True)
    for row in payload.get("closeOrderList", []):
        mode = row.get("closeOrderType")
        if mode and isinstance(mode.get("value"), str):
            text = mode["value"].strip()
            match = _POV.fullmatch(text) or _TWAP_RANGE.fullmatch(text) or _TWAP_DURATION.fullmatch(text)
            if match:
                row["closeOrderType"] = {**mode, "value": match["mode"]}
                for group, name in (
                    ("ratio", "closeOrderPovRatio"),
                    ("start", "closeOrderAlgoStartTime"),
                    ("end", "closeOrderAlgoEndTime"),
                ):
                    value = match.groupdict().get(group)
                    existing: dict[str, Any] = row.get(name) or {}
                    if value is not None and existing.get("value") is None:
                        row[name] = {**mode, "value": value}
        ratio = row.get("closeOrderPovRatio")
        if ratio and isinstance(ratio.get("value"), str):
            match = _POV.fullmatch(ratio["value"].strip())
            if match:
                row["closeOrderPovRatio"] = {**ratio, "value": match["ratio"]}
    return type(candidates).model_validate(payload)
