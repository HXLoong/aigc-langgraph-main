"""通用模型工厂：三角色独立配置模型，厂商协议由显式 provider 决定。

业务只有 parse_instruction 请求 STANDARD；当前验收基线为 DeepSeek Pro。
SDK 和图层均不重试，真实派发次数由调用级 HTTP 守卫检查。
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI
from openai import DefaultAsyncHttpxClient, DefaultHttpxClient
from pydantic import BaseModel, Field, SecretStr

from app.config import LLMProvider, get_settings
from app.llm.budget import before_async_model_request, before_model_request


class ModelOutputCapacityError(ValueError):
    """模型已经用完输出容量，不能把部分结果提交到业务接口。"""


def _http_client_kwargs(trust_env: bool) -> dict[str, Any]:
    """每个 LLM 实例独占连接池，避免缓存重建后复用已关闭的跨 loop 客户端。"""
    kwargs: dict[str, Any] = {
        "http_client": DefaultHttpxClient(trust_env=trust_env, event_hooks={"request": [before_model_request]}),
        "http_async_client": DefaultAsyncHttpxClient(trust_env=trust_env, event_hooks={"request": [before_async_model_request]}),
    }
    if not trust_env:
        kwargs["openai_proxy"] = None
    return kwargs


def _thinking_off_extra_body(provider: LLMProvider) -> dict[str, Any]:
    """仅为已选择的厂商发送关闭思考参数；通用适配不附加私有字段。"""
    if provider == "deepseek":
        return {"thinking": {"type": "disabled"}}
    if provider == "qwen":
        return {"enable_thinking": False}
    return {}


class _ChatLLM(ChatOpenAI):
    """按显式 provider 选择结构化协议，模型名称只作为网关模型标识。"""

    provider: LLMProvider = Field(default="openai_compatible", exclude=True)

    def with_structured_output(self, schema: dict[str, Any] | type | None = None, **kwargs: Any) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        """为兼容模型选择结构化输出协议，不发起额外修复请求。"""
        if self.provider in {"deepseek", "openai_compatible"} and "method" not in kwargs:
            kwargs["method"] = "function_calling"
        return super().with_structured_output(schema, **kwargs)

    async def ainvoke(
        self, input: LanguageModelInput, config: RunnableConfig | None = None,
        *, stop: list[str] | None = None, **kwargs: Any,
    ) -> AIMessage:
        """在模型调用期限内等待一次结果，超时取消当前请求。"""
        budget = self.request_timeout
        seconds = float(budget) if isinstance(budget, (int, float)) else get_settings().llm_timeout_seconds
        async with asyncio.timeout(seconds):
            result = await super().ainvoke(input, config, stop=stop, **kwargs)
        # 即使截断结果恰好是合法 JSON，也不能当作完整批次继续提交。
        if result.response_metadata.get("finish_reason") == "length":
            raise ModelOutputCapacityError("模型输出超出单次解析容量")
        return result


def _build_llm(
    model: str, *, max_tokens: int | None = None, thinking_off: bool = True,
    temperature: float = 0.0, timeout: float | None = None,
) -> ChatOpenAI:
    """文本工厂共用构造：默认温度 0，零重试，调用边界统一计数。"""
    settings = get_settings()
    # 角色与模型别名不参与厂商推断，通用模式不发送厂商扩展。
    body = _thinking_off_extra_body(settings.llm_provider) if thinking_off else {}
    extra: dict[str, Any] = {"extra_body": body} if body else {}
    return _ChatLLM(
        provider=settings.llm_provider,
        model=model,
        base_url=settings.llm_api_base,
        api_key=SecretStr(settings.llm_api_key),
        temperature=temperature,
        timeout=timeout if timeout is not None else settings.llm_timeout_seconds,
        max_tokens=max_tokens or settings.llm_output_max_tokens,
        max_retries=0,
        **extra,
        **_http_client_kwargs(settings.llm_trust_env),
    )


@lru_cache(maxsize=1)
def get_llm_standard() -> ChatOpenAI:
    """STANDARD：本次产品、意图和参数的联合解析模型。"""
    return _build_llm(get_settings().llm_model_standard)


@lru_cache(maxsize=1)
def get_llm_thinking() -> ChatOpenAI:
    """THINKING：离线生成工具角色，不由角色名自动开启思考。"""
    return _build_llm(get_settings().llm_model_thinking)


@lru_cache(maxsize=1)
def get_llm_structured() -> ChatOpenAI:
    """结构化调用复用 STANDARD 配置，不增加第四个模型角色。"""
    return _build_llm(get_settings().llm_model_standard)


@lru_cache(maxsize=1)
def get_llm_complex() -> ChatOpenAI:
    """COMPLEX：保留复杂任务的独立模型配置，当前业务链不使用。"""
    return _build_llm(get_settings().llm_model_complex)


@lru_cache(maxsize=1)
def get_llm_instrument_tool() -> ChatOpenAI:
    """标的工具复用 STANDARD 配置；独立温度与单次超时，不影响企微主图。"""
    return _build_llm(get_settings().llm_model_standard, temperature=0.1, timeout=20.0)
