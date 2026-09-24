"""LLM 客户端统一工厂（ADR 0020：全环境统一 DeepSeek-V4-pro）。

全部走 OpenAI 兼容 API，用 langchain_openai.ChatOpenAI。
vendor 由 .env 的 QWEN_API_BASE / QWEN_API_KEY / QWEN_MODEL_* 切换
（`qwen_` 前缀是历史命名，当前全部指向 DeepSeek-V4-pro）。

当前策略：全部节点统一关闭思考模式，以速度为先
（4-7s/长 prompt vs thinking 模式 60-180s）。
关闭参数两家不同，见 _thinking_off_extra_body。

保留 standard / thinking / structured / complex / vl 5 个工厂函数，是为了按节点
切换模型时只改 .env 或一个函数；构造细节统一在 _build_llm。
"""
from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI
from openai import DefaultAsyncHttpxClient, DefaultHttpxClient
from pydantic import BaseModel, SecretStr

from app.config import get_settings


def _http_client_kwargs(trust_env: bool) -> dict[str, Any]:
    """每个 LLM 实例独占连接池，避免缓存重建后复用已关闭的跨 loop 客户端。"""
    kwargs: dict[str, Any] = {
        "http_client": DefaultHttpxClient(trust_env=trust_env),
        "http_async_client": DefaultAsyncHttpxClient(trust_env=trust_env),
    }
    if not trust_env:
        kwargs["openai_proxy"] = None
    return kwargs


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

    def with_structured_output(self, schema: dict[str, Any] | type | None = None, **kwargs: Any) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        if _is_deepseek(self.model_name) and "method" not in kwargs:
            kwargs["method"] = "function_calling"
        return super().with_structured_output(schema, **kwargs)

    async def ainvoke(
        self, input: LanguageModelInput, config: RunnableConfig | None = None,
        *, stop: list[str] | None = None, **kwargs: Any,
    ) -> AIMessage:
        budget = self.request_timeout
        seconds = float(budget) if isinstance(budget, (int, float)) else get_settings().llm_timeout_seconds
        async with asyncio.timeout(seconds):
            return await super().ainvoke(input, config, stop=stop, **kwargs)


def _build_llm(model: str, *, max_tokens: int | None = None, thinking_off: bool = True) -> ChatOpenAI:
    """所有 LLM 工厂共用的构造：温度 0、SDK 不重试（重试归图的 RetryPolicy，ADR 0024 D3）。"""
    settings = get_settings()
    extra: dict[str, Any] = {"extra_body": _thinking_off_extra_body(model)} if thinking_off else {}
    return _ChatLLM(
        model=model,
        base_url=settings.qwen_api_base,
        api_key=SecretStr(settings.qwen_api_key),
        temperature=0.0,
        timeout=settings.llm_timeout_seconds,
        max_tokens=max_tokens or settings.llm_output_max_tokens,
        max_retries=0,
        **extra,
        **_http_client_kwargs(settings.llm_trust_env),
    )


@lru_cache(maxsize=1)
def get_qwen_standard() -> ChatOpenAI:
    """标准模型：意图识别 / 路由（非 thinking）。"""
    return _build_llm(get_settings().qwen_model_standard)


@lru_cache(maxsize=1)
def get_qwen_thinking() -> ChatOpenAI:
    """名义"思考型"模型（当前统一关 thinking 以求速度）；未来如需开 thinking 只改本函数。"""
    return _build_llm(get_settings().qwen_model_thinking)


@lru_cache(maxsize=1)
def get_qwen_structured() -> ChatOpenAI:
    """专用于 with_structured_output（非 thinking）。"""
    return _build_llm(get_settings().qwen_model_standard)


@lru_cache(maxsize=1)
def get_qwen_complex() -> ChatOpenAI:
    """复杂提取专用（当前与 standard 同模型，保留接口供按节点切换）。"""
    return _build_llm(get_settings().qwen_model_complex)


@lru_cache(maxsize=1)
def get_qwen_vl() -> ChatOpenAI:
    """视觉模型：图片 OCR / 截图识别。"""
    settings = get_settings()
    return _build_llm(
        settings.qwen_model_vl, max_tokens=settings.llm_vision_max_tokens, thinking_off=False,
    )
