"""互换本地参数拒绝；异常仅携带字段名，不包含用户提供的数值。"""
from __future__ import annotations


class AmbiguousActionError(ValueError):
    """暂定或历史成交描述不能自动解释为本轮新委托。"""

    def __init__(self) -> None:
        super().__init__("暂定或历史动作不能作为新的交易指令，请明确本轮动作。")


class NonPositiveQuantityError(ValueError):
    """委托数量字段展开后不大于零。"""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} 必须大于零")
