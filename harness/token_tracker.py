"""Harness LLM token 追踪（灰度成本观测）。

通过 LangChain BaseCallbackHandler 拦截每次 LLM 响应，把 usage_metadata
累计到 TokenUsage（按模型分组），不侵入业务节点代码。

集成点：以 callback 注入任意 graph；当前无生产消费方，保留供 harness 侧成本观测复用。

为什么不用 app/observability/metrics.py:emit_llm_tokens：
  - emit_llm_tokens 是为生产 /metrics endpoint 设计（进程级 Counter）
  - harness 关心**单次 run** 的 token 累计 + 报告（per-run 隔离）
  - 两者并行不冲突；本模块未来可选择性 forward 到 metrics
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TokenUsage(BaseModel):
    """单次 harness run 的 token 使用累计。"""

    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    by_model: dict[str, dict[str, int]] = Field(default_factory=dict)

    def merge(self, other: TokenUsage) -> TokenUsage:
        """合并两个 TokenUsage（用于跨 case 聚合）。返回新对象，不修改 self。"""
        merged = TokenUsage(
            call_count=self.call_count + other.call_count,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            by_model={
                m: {"prompt": v["prompt"], "completion": v["completion"]}
                for m, v in self.by_model.items()
            },
        )
        for model, counts in other.by_model.items():
            slot = merged.by_model.setdefault(
                model, {"prompt": 0, "completion": 0}
            )
            slot["prompt"] += counts.get("prompt", 0)
            slot["completion"] += counts.get("completion", 0)
        return merged


class TokenTracker(BaseCallbackHandler):
    """LangChain callback：累计 LLM token 使用。

    支持两种 LangChain usage 数据格式：
    1. response.llm_output["token_usage"]（旧版 / OpenAI 风格）
    2. AIMessage.usage_metadata（LangChain 0.2+ 统一 schema）
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: {"prompt": 0, "completion": 0}
        )

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """LangChain hook：LLM 响应完成。"""
        try:
            pt, ct, model = self._extract_usage(response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("token_tracker: extract_usage failed: %s", exc)
            return
        if pt == 0 and ct == 0:
            # 没拿到 usage 不计数（避免误增 call_count）
            return

        self.call_count += 1
        self.prompt_tokens += pt
        self.completion_tokens += ct
        self._by_model[model]["prompt"] += pt
        self._by_model[model]["completion"] += ct

    @staticmethod
    def _extract_usage(response: LLMResult) -> tuple[int, int, str]:
        """从 LLMResult 抽 (prompt_tokens, completion_tokens, model_name)。

        优先级：
          1. response.llm_output['token_usage']（同时含 'model_name'）
          2. AIMessage.usage_metadata（input_tokens / output_tokens）

        返回 (0, 0, 'unknown') 表示拿不到。
        """
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

        # 兜底：从 AIMessage.usage_metadata 取
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
                # AIMessage 也可能带 response_metadata.model_name
                rm = getattr(msg, "response_metadata", None) or {}
                if isinstance(rm, dict):
                    model = rm.get("model_name") or model
                if pt or ct:
                    return pt, ct, model

        return 0, 0, model

    def to_usage(self) -> TokenUsage:
        """快照成 TokenUsage（用于序列化到 RunResult / summary）。"""
        return TokenUsage(
            call_count=self.call_count,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.prompt_tokens + self.completion_tokens,
            by_model={
                model: dict(counts) for model, counts in self._by_model.items()
            },
        )


def aggregate(usages: list[TokenUsage]) -> TokenUsage:
    """跨 case 聚合 token 使用。"""
    out = TokenUsage()
    for u in usages:
        out = out.merge(u)
    return out


__all__ = ["TokenTracker", "TokenUsage", "aggregate"]
