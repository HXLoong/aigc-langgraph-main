"""LLM 客户端封装（标准模型客户端，非仅 Qwen —— ADR 0018）。

全部走 OpenAI 兼容 API，用 langchain_openai.ChatOpenAI。
vendor 由 .env 的 QWEN_API_BASE / QWEN_API_KEY / QWEN_MODEL_* 切换
（`qwen_` 前缀是历史通用命名，现场=DeepSeek-v4-pro，开发期=Qwen）。

当前策略：全部节点统一关闭思考模式，以速度为先
（4-7s/长 prompt vs thinking 模式 60-180s）。
关闭参数两家不同，见 _thinking_off_extra_body。

保留 standard / thinking / structured / complex 4 个工厂函数，是为了：
1. 兼容现有节点的 import 路径
2. 未来可能给特定节点切回 thinking 时改一个函数即可
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI
from openai import DefaultAsyncHttpxClient, DefaultHttpxClient

from app.config import get_settings


def _http_client_kwargs(trust_env: bool) -> dict[str, Any]:
    """按 LLM 独立配置连接，非缓存工厂也独占连接池，避免跨 event loop 复用。"""
    if trust_env:
        return {}
    return {
        "http_client": DefaultHttpxClient(trust_env=False),
        "http_async_client": DefaultAsyncHttpxClient(trust_env=False),
        "openai_proxy": None,
    }


def _is_deepseek(model: str) -> bool:
    """识别原生名和网关别名中的 DeepSeek 段，保留请求里的完整模型名。"""
    return re.search(r"(?:^|[-_/:])deepseek(?:$|[-_/:])", model, re.IGNORECASE) is not None


def _thinking_off_extra_body(model: str) -> dict[str, Any]:
    """按 vendor 返回"关闭思考模式"的 extra_body。

    DeepSeek 会静默忽略 Qwen 的 enable_thinking 参数（默认仍开思考），
    必须用它自己的 thinking.type=disabled；Qwen/dashscope 反之。
    """
    if _is_deepseek(model):
        return {"thinking": {"type": "disabled"}}
    return {"enable_thinking": False}


class _ChatLLM(ChatOpenAI):
    """ChatOpenAI 的 vendor 适配薄层。

    DeepSeek 的 OpenAI 兼容接口不支持 response_format=json_schema
    （400 "This response_format type is unavailable now"），而
    langchain_openai 的 with_structured_output 默认走 json_schema。
    业务代码 20 处调用点均不传 method，故在此统一降级为 function_calling。
    显式传入的 method 不覆盖；Qwen 走 langchain 默认行为。
    """

    def with_structured_output(self, schema=None, **kwargs):  # type: ignore[override]
        if _is_deepseek(self.model_name) and "method" not in kwargs:
            kwargs["method"] = "function_calling"
        return super().with_structured_output(schema, **kwargs)


@lru_cache(maxsize=1)
def get_qwen_standard() -> ChatOpenAI:
    """标准模型：意图识别 / 路由（非 thinking）。"""
    settings = get_settings()
    return _ChatLLM(
        model=settings.qwen_model_standard,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        extra_body=_thinking_off_extra_body(settings.qwen_model_standard),
        **_http_client_kwargs(settings.llm_trust_env),
    )


@lru_cache(maxsize=1)
def get_qwen_thinking() -> ChatOpenAI:
    """名义"思考型" Qwen（当前统一关 thinking 以求速度）。

    Agent 多步推理 / 参数提取节点继续 import 这个名字，未来如需开 thinking
    只改本函数即可。
    """
    settings = get_settings()
    return _ChatLLM(
        model=settings.qwen_model_thinking,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        extra_body=_thinking_off_extra_body(settings.qwen_model_thinking),
        **_http_client_kwargs(settings.llm_trust_env),
    )


def make_qwen_thinking() -> ChatOpenAI:
    """非缓存工厂：每次返回新实例，供跨 event loop 场景使用（如 infer_code 线程）。

    不加 @lru_cache：lru_cache 单例在主 loop 创建后，若在子线程 asyncio.run()
    里复用，httpx 连接池绑定旧 loop，污染主 loop 客户端导致 Connection error。
    """
    settings = get_settings()
    return _ChatLLM(
        model=settings.qwen_model_thinking,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        extra_body=_thinking_off_extra_body(settings.qwen_model_thinking),
        **_http_client_kwargs(settings.llm_trust_env),
    )


@lru_cache(maxsize=1)
def get_qwen_structured() -> ChatOpenAI:
    """专用于 with_structured_output（非 thinking）。"""
    settings = get_settings()
    return _ChatLLM(
        model=settings.qwen_model_standard,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        extra_body=_thinking_off_extra_body(settings.qwen_model_standard),
        **_http_client_kwargs(settings.llm_trust_env),
    )


@lru_cache(maxsize=1)
def get_qwen_complex() -> ChatOpenAI:
    """复杂提取专用（当前 = standard，保留接口供未来切回 235b）。"""
    settings = get_settings()
    return _ChatLLM(
        model=settings.qwen_model_complex,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        extra_body=_thinking_off_extra_body(settings.qwen_model_complex),
        **_http_client_kwargs(settings.llm_trust_env),
    )


@lru_cache(maxsize=1)
def get_qwen_vl() -> ChatOpenAI:
    """视觉 Qwen：图片 OCR / 截图识别。"""
    settings = get_settings()
    return _ChatLLM(
        model=settings.qwen_model_vl,
        base_url=settings.qwen_api_base,
        api_key=settings.qwen_api_key,
        temperature=0.0,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        **_http_client_kwargs(settings.llm_trust_env),
    )
