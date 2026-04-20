"""LLM 客户端封装。

Qwen 系列走 OpenAI 兼容 API，用 langchain_openai.ChatOpenAI。
不同任务选择不同型号：
- 路由 / 意图识别：standard（qwen3-30b-a3b）
- 复杂参数提取：thinking（带推理）
- 图片识别：vl（视觉模型）
"""
from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


@lru_cache(maxsize=1)
def get_qwen_standard() -> ChatOpenAI:
    """标准 Qwen 模型：意图识别、路由。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_standard,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=30,
        max_retries=2,
    )


@lru_cache(maxsize=1)
def get_qwen_thinking() -> ChatOpenAI:
    """思考型 Qwen：复杂参数提取、Agent 推理。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_thinking,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=60,
        max_retries=2,
    )


@lru_cache(maxsize=1)
def get_qwen_vl() -> ChatOpenAI:
    """视觉 Qwen：图片 OCR / 截图识别。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_vl,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=60,
        max_retries=2,
    )
