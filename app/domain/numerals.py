"""序号与中文数字解析的唯一实现（原先散落在确认协议、三个子图的订单号模块与期限换算中）。

调用方先用各自的正则限定输入字符集，这里只做数值换算：
- `chinese_int`：纯中文数字（支持 十 / 百 / 千 组合），遇到其它字符返回 None
- `ordinal_int`：阿拉伯数字（可带正负号）或中文数字；无法解析返回 None
- `require_ordinal`：同上，但无法解析时抛 ValueError（调用方正则已保证合法时使用）
"""
from __future__ import annotations

#: 中文数字字符 → 数值
CN_DIGITS: dict[str, int] = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_UNITS = {"十": 10, "百": 100, "千": 1000}


def chinese_int(text: str) -> int | None:
    """解析中文数字（≤ 千级组合），如 两千 → 2000、三千五百 → 3500、十二 → 12。"""
    total = current = 0
    for char in text:
        if char in CN_DIGITS:
            current = CN_DIGITS[char]
        elif char in _UNITS:
            total += (current or 1) * _UNITS[char]
            current = 0
        else:
            return None
    return total + current


def ordinal_int(token: str) -> int | None:
    """序号词 → int：阿拉伯数字（可带正负号）直接换算，否则按中文数字解析。"""
    if token.lstrip("+-").isdigit():
        return int(token)
    return chinese_int(token)


def require_ordinal(token: str) -> int:
    """同 `ordinal_int`，无法解析时抛 ValueError。"""
    value = ordinal_int(token)
    if value is None:
        raise ValueError(f"无法解析序号：{token!r}")
    return value


__all__ = ["CN_DIGITS", "chinese_int", "ordinal_int", "require_ordinal"]
