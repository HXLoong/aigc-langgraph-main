"""标的识别子图的 Pydantic 输出模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TokenizeOutput(BaseModel):
    """分词节点输出：关键词列表 + 是否需要重新提取。"""

    keywords: list[str] = Field(
        default_factory=list,
        description="提取到的标的关键词列表（去重去空，保持出现顺序）",
    )
    needs_refinement: bool = Field(
        default=False,
        description="关键词质量不足，需要用更谨慎的提示词重新提取",
    )
