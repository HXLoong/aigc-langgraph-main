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
    """标准 Qwen 模型：意图识别、路由（全开 thinking 测试）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_standard,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=90,
        max_retries=2,
        extra_body={"enable_thinking": True},
    )


@lru_cache(maxsize=1)
def get_qwen_thinking() -> ChatOpenAI:
    """思考型 Qwen：复杂参数提取、Agent 推理。启用 enable_thinking 触发链式推理。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_thinking,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=90,
        max_retries=2,
        extra_body={"enable_thinking": True},
    )


@lru_cache(maxsize=1)
def get_qwen_structured() -> ChatOpenAI:
    """Qwen 模型专用于 with_structured_output（json_mode + thinking 测试）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_standard,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=90,
        max_retries=2,
        extra_body={"enable_thinking": True},
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
