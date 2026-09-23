"""互换本地参数拒绝；异常仅携带字段名，不包含用户提供的数值。"""
from __future__ import annotations


class NonPositiveQuantityError(ValueError):
    """委托数量字段展开后不大于零。"""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} 必须大于零")
