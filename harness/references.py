"""Resolve fixture expectations from the actual quoted card, never from model output."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuoteReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "quote.order_id", "quote.order_ids", "quote.counterparty", "quote.holding_contract",
    ] = Field(alias="$ref")
    position: int | None = Field(default=None, gt=0, strict=True)
    option: str | None = Field(default=None, pattern=r"^[A-Z]$")

    @model_validator(mode="after")
    def check_selector(self) -> QuoteReference:
        if self.source == "quote.counterparty":
            if self.option is None or self.position is not None:
                raise ValueError("counterparty reference requires only an option")
        elif self.option is not None:
            raise ValueError("option only applies to counterparty references")
        if self.source == "quote.order_ids" and self.position is not None:
            raise ValueError("order_ids selects the complete quoted scope")
        return self


class ReferenceResolutionError(ValueError):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(reason)
        self.path = path


_ORDERS = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"((?:Q|CO|H)-\d{8}-[A-Za-z0-9]+)(?![A-Za-z0-9-])",
)
_CONTRACTS = re.compile(r"(?:^|\n)\s*合约编号\s*[:：]\s*(OPTG?-[A-Za-z0-9]+)")
_OPTIONS = re.compile(
    r"(?<![A-Za-z0-9])([A-Z])[.、）)]\s*([^\n]+?)"
    r"(?=\s+[A-Z][.、）)]|\n|$)",
)


def _card_text(quote: str) -> str:
    lines = []
    for line in quote.splitlines():
        if line.strip().startswith(("例如", "示例")):
            break
        lines.append(line)
    return "\n".join(lines)


def _resolve(reference: QuoteReference, quote: str) -> str | list[str]:
    text = _card_text(quote)
    values: list[str]
    if reference.source == "quote.counterparty":
        values = list(dict.fromkeys(value.strip() for option, value in _OPTIONS.findall(text)
                                    if option == reference.option))
    else:
        pattern = _CONTRACTS if reference.source == "quote.holding_contract" else _ORDERS
        values = list(dict.fromkeys(pattern.findall(text)))
    if not values:
        raise ValueError("quoted reference is missing")
    if reference.source == "quote.order_ids":
        return values
    if reference.position is not None:
        if reference.position > len(values):
            raise ValueError("quoted position is out of range")
        return values[reference.position - 1]
    if len(values) != 1:
        raise ValueError("quoted reference is ambiguous")
    return values[0]


def resolve_expected_references(value: Any, quote: str, path: str = "") -> Any:
    """Copy the expectation tree and replace explicit $ref leaves; invalid refs fail closed."""
    if isinstance(value, dict):
        if "$ref" in value:
            try:
                return _resolve(QuoteReference.model_validate(value), quote)
            except ValueError as exc:
                raise ReferenceResolutionError(path, "cannot resolve quoted expectation: " + str(exc)) from exc
        return {key: resolve_expected_references(child, quote, f"{path}.{key}" if path else key)
                for key, child in value.items()}
    if isinstance(value, list):
        return [resolve_expected_references(child, quote, f"{path}[{i}]") for i, child in enumerate(value)]
    return value


def validate_expected_references(value: Any, path: str = "expected") -> list[str]:
    """Validate the declaration without requiring the future runtime quote."""
    errors: list[str] = []
    if isinstance(value, dict):
        if "$ref" in value:
            try:
                QuoteReference.model_validate(value)
            except ValueError as exc:
                errors.append(f"{path}: invalid $ref: {exc}")
        else:
            for key, child in value.items():
                errors.extend(validate_expected_references(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            errors.extend(validate_expected_references(child, f"{path}[{i}]"))
    return errors
