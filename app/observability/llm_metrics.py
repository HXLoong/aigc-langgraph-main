"""LLM 调用指标 callback（ADR 0024 D5）。

`emit_llm_call` / `emit_llm_tokens` 此前零调用：`llm_failure_high` 告警永不触发、成本日报恒空。
业务代码手工 emit 不可靠，改由 LangChain callback 在 `on_llm_end` / `on_llm_error` 自动打点：
- 模型名：`on_*_start` 的 invocation_params.model_name（错误路径没有 response，只能从这里取）
- 节点名：LangGraph 自动注入的 `metadata["langgraph_node"]`
- token：兼容 `llm_output.token_usage`（OpenAI 风格）与 `AIMessage.usage_metadata`（LangChain 统一 schema）
callback 绝不抛异常（观测不阻断业务）。
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.observability.metrics import emit_llm_cache, emit_llm_call, emit_llm_tokens

logger = logging.getLogger(__name__)


def extract_usage(response: LLMResult) -> tuple[int, int, str]:
    """从 LLMResult 抽 (prompt_tokens, completion_tokens, model_name)；拿不到 → (0, 0, "unknown")。"""
    model = "unknown"
    llm_output = response.llm_output or {}
    if isinstance(llm_output, dict):
        model = llm_output.get("model_name") or model
        usage = llm_output.get("token_usage") or {}
        if isinstance(usage, dict) and usage:
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            if pt or ct:
                return pt, ct, model
    for gen_list in response.generations or []:
        for gen in gen_list:
            msg = getattr(gen, "message", None)
            if msg is None:
                continue
            um = getattr(msg, "usage_metadata", None) or {}
            if not isinstance(um, dict) or not um:
                continue
            pt = int(um.get("input_tokens") or 0)
            ct = int(um.get("output_tokens") or 0)
            rm = getattr(msg, "response_metadata", None) or {}
            if isinstance(rm, dict):
                model = rm.get("model_name") or model
            if pt or ct:
                return pt, ct, model
    return 0, 0, model


def _classify_error(error: BaseException) -> str:
    name = type(error).__name__.lower()
    return "timeout" if "timeout" in name else "error"


def extract_cache_usage(response: LLMResult, prompt_tokens: int) -> tuple[str, int, int]:
    """Use one provider representation; absent cache usage is not a cache miss."""
    output = response.llm_output or {}
    sources = [output.get("token_usage", {})] if isinstance(output, dict) else []
    for generations in response.generations:
        for generation in generations:
            message = getattr(generation, "message", None)
            metadata = getattr(message, "response_metadata", None) or {}
            if isinstance(metadata, dict):
                sources.append(metadata.get("token_usage", {}))
            sources.append(getattr(message, "usage_metadata", None) or {})
    for usage in sources:
        if not isinstance(usage, dict):
            continue
        if "prompt_cache_hit_tokens" in usage:
            hit = usage["prompt_cache_hit_tokens"]
        else:
            details = usage.get("prompt_tokens_details") or {}
            unified = usage.get("input_token_details") or {}
            if isinstance(details, dict) and "cached_tokens" in details:
                hit = details["cached_tokens"]
            elif isinstance(unified, dict) and "cache_read" in unified:
                hit = unified["cache_read"]
            else:
                continue
        if type(hit) is not int or not 0 <= hit <= prompt_tokens:
            return "invalid", 0, 0
        miss = usage.get("prompt_cache_miss_tokens", prompt_tokens - hit)
        if type(miss) is not int or miss < 0 or hit + miss != prompt_tokens:
            return "invalid", 0, 0
        return "reported", hit, miss
    return "unreported", 0, 0


class LLMMetricsCallback(BaseCallbackHandler):
    """挂在每次 graph 调用的 config["callbacks"] 上（app/api/routes.py）。"""

    raise_error = False

    def __init__(self) -> None:
        super().__init__()
        self._runs: dict[UUID, tuple[str, str | None]] = {}  # run_id → (model, node)

    # ---- start：记模型名 + 节点名 ----
    def _remember(self, run_id: UUID, metadata: dict[str, Any] | None, kwargs: dict[str, Any]) -> None:
        params = kwargs.get("invocation_params") or {}
        model = str(params.get("model_name") or params.get("model") or "unknown")
        node = (metadata or {}).get("langgraph_node")
        self._runs[run_id] = (model, str(node) if node else None)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):  # type: ignore[no-untyped-def]
        try:
            self._remember(run_id, metadata, kwargs)
        except Exception:  # noqa: BLE001
            logger.debug("llm_metrics: on_chat_model_start ignored", exc_info=True)

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):  # type: ignore[no-untyped-def]
        try:
            self._remember(run_id, metadata, kwargs)
        except Exception:  # noqa: BLE001
            logger.debug("llm_metrics: on_llm_start ignored", exc_info=True)

    # ---- end / error：打点 ----
    def on_llm_end(self, response: LLMResult, *, run_id: UUID, parent_run_id=None, tags=None, **kwargs):  # type: ignore[no-untyped-def]
        try:
            start_model, node = self._runs.pop(run_id, ("unknown", None))
            pt, ct, model = extract_usage(response)
            if model == "unknown":
                model = start_model
            if pt == 0 and ct == 0:
                return
            emit_llm_call(model=model, status="ok")
            emit_llm_tokens(model=model, prompt_tokens=pt, completion_tokens=ct, node=node)
            status, hit, miss = extract_cache_usage(response, pt)
            emit_llm_cache(model, node, status, hit, miss)
        except Exception:  # noqa: BLE001 - 观测不阻断业务
            logger.debug("llm_metrics: on_llm_end ignored", exc_info=True)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, parent_run_id=None, tags=None, **kwargs):  # type: ignore[no-untyped-def]
        try:
            model, _node = self._runs.pop(run_id, ("unknown", None))
            emit_llm_call(model=model, status=_classify_error(error))
        except Exception:  # noqa: BLE001
            logger.debug("llm_metrics: on_llm_error ignored", exc_info=True)


__all__ = ["LLMMetricsCallback", "extract_usage"]
