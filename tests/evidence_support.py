"""Explicit mock outputs matching the new evidence contract; no runtime patches."""
from pydantic import BaseModel

from app.extraction.candidates import candidate_model


def candidate_output(model: BaseModel, *, origin: str = "raw", origins: dict[str, str] | None = None,
                     spellings: dict[str, str] | None = None) -> BaseModel:
    def convert(value, alias=""):
        if isinstance(value, BaseModel):
            return {info.alias or name: convert(getattr(value, name), info.alias or name)
                    for name, info in type(value).model_fields.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        if value is None:
            return None
        literal = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        text = (spellings or {}).get(literal, literal)
        return {"value": text, "evidence": text, "confidence": 1.0,
                "origin": (origins or {}).get(alias, origin)}
    return candidate_model(type(model)).model_validate(convert(model))


def swap_candidate_output(model: BaseModel) -> BaseModel:
    return candidate_output(model, spellings={
        "BUY": "买入", "SELL": "卖出", "SHORT_OPEN": "卖空", "SHORT_CLOSE": "平空",
        "LimitOrder": "限价", "MarketOrder": "市价", "SHARE": "股", "HAND": "手",
        "AMOUNT": "元", "A_SHARE": "A股", "HK_STOCK": "港股", "US_STOCK": "美股",
    })
