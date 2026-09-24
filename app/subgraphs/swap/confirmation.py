"""兼容互换确认协议入口；七条确认共用同一个确定性校验器。"""
import re

from app.domain.confirmation import (
    ALIASES,
    Confirmation,
    confirmation_action,
    parse_confirmation,
)


def is_confirmation(raw: str | None) -> bool:
    text = (raw or "").strip()
    return confirmation_action(raw) == "place" and (text in ALIASES["place"] or re.fullmatch(
        r"序号[1-9][0-9]*(?:、序号[1-9][0-9]*)*，(?:" + "|".join(ALIASES["place"]) + r")", text,
    ) is not None)


__all__ = ["Confirmation", "is_confirmation", "parse_confirmation"]
