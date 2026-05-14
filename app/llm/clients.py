"""LLM 客户端封装。

Qwen 系列走 OpenAI 兼容 API，用 langchain_openai.ChatOpenAI。

当前策略（2026-05-14）：
全部节点统一用 qwen3.5-35b-a3b + enable_thinking=False，
以速度为先（4-7s/长 prompt vs thinking 模式 60-180s），与内部部署对齐。

保留 standard / thinking / structured / complex 4 个工厂函数，是为了：
1. 兼容现有节点的 import 路径
2. 未来可能给特定节点切回 thinking 时改一个函数即可
"""
from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


@lru_cache(maxsize=1)
def get_qwen_standard() -> ChatOpenAI:
    """标准 Qwen：意图识别 / 路由（非 thinking）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_standard,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=60,
        max_retries=2,
        extra_body={"enable_thinking": False},
    )


@lru_cache(maxsize=1)
def get_qwen_thinking() -> ChatOpenAI:
    """名义"思考型" Qwen（当前统一关 thinking 以求速度）。

    Agent 多步推理 / 参数提取节点继续 import 这个名字，未来如需开 thinking
    只改本函数即可。
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_thinking,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=60,
        max_retries=2,
        extra_body={"enable_thinking": False},
    )


def make_qwen_thinking() -> ChatOpenAI:
    """非缓存工厂：每次返回新实例，供跨 event loop 场景使用（如 infer_code 线程）。

    不加 @lru_cache：lru_cache 单例在主 loop 创建后，若在子线程 asyncio.run()
    里复用，httpx 连接池绑定旧 loop，污染主 loop 客户端导致 Connection error。
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_thinking,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=60,
        max_retries=2,
        extra_body={"enable_thinking": False},
    )


@lru_cache(maxsize=1)
def get_qwen_structured() -> ChatOpenAI:
    """Qwen 模型专用于 with_structured_output（非 thinking）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_standard,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=60,
        max_retries=2,
        extra_body={"enable_thinking": False},
    )


@lru_cache(maxsize=1)
def get_qwen_complex() -> ChatOpenAI:
    """复杂提取专用（当前 = standard，保留接口供未来切回 235b）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.qwen_model_complex,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=60,
        max_retries=2,
        extra_body={"enable_thinking": False},
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
