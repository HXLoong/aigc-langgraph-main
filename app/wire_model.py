"""Python 字段用 snake_case；JSON、LLM schema 和 checkpoint 保留协议 alias。"""
from typing import Any

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    """接受字段名和 alias，默认按 alias 导出（兼容 Pydantic 2.8+）。"""

    model_config = ConfigDict(populate_by_name=True)

    def model_dump(self, *, by_alias: bool | None = True, **kwargs: Any) -> dict[str, Any]:
        return super().model_dump(by_alias=by_alias, **kwargs)

    def model_dump_json(self, *, by_alias: bool | None = True, **kwargs: Any) -> str:
        return super().model_dump_json(by_alias=by_alias, **kwargs)
