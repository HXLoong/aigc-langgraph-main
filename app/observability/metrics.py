"""业务指标埋点（C1.5 / Issue #50）。

提供轻量级的内存 MetricsCollector + Prometheus 兼容输出，承载 ADR 0017
量化退出门所需的全部核心指标：

- 每意图响应延迟（P50/P95/P99）—— Histogram
- 节点级 PASS/FAIL 率 —— Counter（labels: node, status）
- Fallback render 触发率 —— Counter
- HITL interrupt 触发率 —— Counter
- LLM 调用成功/失败率 —— Counter（labels: model, status）

设计原则：
- **不依赖外部存储**：纯内存，进程重启清零；趋势数据由 LangFuse trace 兜底
- **不阻塞业务**：所有 emit 调用是 O(1) 同步操作，无 I/O
- **可观测降级**：metrics 模块自身故障不能影响业务主流程（all-try-except）
- **Prometheus 兼容**：`/metrics` endpoint 输出标准 exposition 格式

字段命名约定（与 ADR 0017 量化指标对齐）：
- `otc_agent_node_total{node,status}` —— 节点级 counter
- `otc_agent_intent_latency_ms{product_type,intent}` —— 延迟 histogram
- `otc_agent_fallback_total{reason}` —— fallback render counter
- `otc_agent_hitl_total{node}` —— HITL counter
- `otc_agent_llm_total{model,status}` —— LLM counter
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构：简单的 Histogram（bucket-based）
# ============================================================

# 默认延迟 bucket（毫秒）—— 覆盖典型 chat agent 响应区间
_LATENCY_BUCKETS_MS = [
    100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000, float("inf")
]


class _Histogram:
    """轻量 Histogram。线程安全。

    内部结构：bucket 计数 + 总和 + 总次数。可计算 P50/P95/P99 估算（基于 bucket 边界）。
    """

    def __init__(self, buckets: list[float] | None = None) -> None:
        self._buckets = buckets or _LATENCY_BUCKETS_MS
        # 普通 dict + .get(b, 0)：读时不创建键，避免 defaultdict 读时副作用
        self._counts: dict[float, int] = {}
        self._sum: float = 0.0
        self._total: int = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._total += 1
            for b in self._buckets:
                if value <= b:
                    self._counts[b] = self._counts.get(b, 0) + 1

    def quantile(self, q: float) -> float | None:
        """估算 q 分位（如 q=0.95 -> P95）。基于 bucket 边界，返回上界。"""
        with self._lock:
            if self._total == 0:
                return None
            target = self._total * q
            for b in self._buckets:
                cumulative = self._counts.get(b, 0)
                if cumulative >= target:
                    return b
            return self._buckets[-1]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "count": self._total,
                "sum": self._sum,
                "buckets": {str(b): self._counts.get(b, 0) for b in self._buckets},
            }


# ============================================================
# MetricsCollector（全局单例）
# ============================================================


class MetricsCollector:
    """业务指标采集器。线程安全。

    内部维护几个独立的 counter 与 histogram，按 label 维度区分。
    Counter 用 dict[tuple, int] 存（tuple = labels 排序后的值）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # counter[name][labels_tuple] = count
        self._counters: dict[str, dict[tuple, int]] = defaultdict(lambda: defaultdict(int))
        # histogram[name][labels_tuple] = _Histogram
        self._histograms: dict[str, dict[tuple, _Histogram]] = defaultdict(dict)

    # ---- emit API ----

    def inc_counter(self, name: str, labels: dict[str, str] | None = None, value: int = 1) -> None:
        """计数器 +N。labels 可选。"""
        try:
            key = self._labels_to_key(labels)
            with self._lock:
                self._counters[name][key] += value
        except Exception as exc:  # noqa: BLE001 - 监控不能影响业务
            logger.warning("metrics.inc_counter failed: %s", exc)

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """直方图记一次观测。labels 可选。"""
        try:
            key = self._labels_to_key(labels)
            with self._lock:
                if key not in self._histograms[name]:
                    self._histograms[name][key] = _Histogram()
            self._histograms[name][key].observe(value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("metrics.observe_histogram failed: %s", exc)

    # ---- query API ----

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        key = self._labels_to_key(labels)
        with self._lock:
            return self._counters[name].get(key, 0)

    def get_quantile(
        self,
        name: str,
        q: float,
        labels: dict[str, str] | None = None,
    ) -> float | None:
        key = self._labels_to_key(labels)
        hist = self._histograms[name].get(key)
        if hist is None:
            return None
        return hist.quantile(q)

    # ---- prometheus exposition ----

    def render_prometheus(self) -> str:
        """输出 Prometheus exposition 格式（text/plain v0.0.4）。"""
        with self._lock:
            lines: list[str] = []
            # Counters
            for name, items in self._counters.items():
                lines.append(f"# TYPE {name} counter")
                for key, count in items.items():
                    label_str = self._key_to_labels(key)
                    lines.append(f"{name}{label_str} {count}")
            # Histograms
            for name, items in self._histograms.items():
                lines.append(f"# TYPE {name} histogram")
                for key, hist in items.items():
                    label_str_prefix = self._key_to_labels(key, trailing_comma=True)
                    snap = hist.snapshot()
                    for bucket, count in snap["buckets"].items():
                        # bucket=+Inf 用 +Inf 字面量
                        bucket_label = "+Inf" if bucket == "inf" else bucket
                        lines.append(
                            f'{name}_bucket{{{label_str_prefix}le="{bucket_label}"}} {count}'
                        )
                    lines.append(f"{name}_sum{self._key_to_labels(key)} {snap['sum']}")
                    lines.append(f"{name}_count{self._key_to_labels(key)} {snap['count']}")
            return "\n".join(lines) + "\n"

    # ---- 内部工具 ----

    @staticmethod
    def _labels_to_key(labels: dict[str, str] | None) -> tuple:
        if not labels:
            return ()
        return tuple(sorted(labels.items()))

    @staticmethod
    def _key_to_labels(key: tuple, trailing_comma: bool = False) -> str:
        if not key:
            return "" if not trailing_comma else ""
        body = ",".join(f'{k}="{v}"' for k, v in key)
        if trailing_comma:
            return f"{body},"
        return "{" + body + "}"

    # ---- 重置（测试用）----

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


# ============================================================
# 全局单例
# ============================================================


_collector_singleton: MetricsCollector | None = None


def get_collector() -> MetricsCollector:
    """全局单例。"""
    global _collector_singleton
    if _collector_singleton is None:
        _collector_singleton = MetricsCollector()
    return _collector_singleton


# ============================================================
# 便捷 emit helper（在业务代码 / safe_node 中调用）
# ============================================================


# 指标名称（与文档 / Prometheus 查询保持一致）
METRIC_NODE_TOTAL = "otc_agent_node_total"
METRIC_INTENT_LATENCY = "otc_agent_intent_latency_ms"
METRIC_FALLBACK_TOTAL = "otc_agent_fallback_total"
METRIC_HITL_TOTAL = "otc_agent_hitl_total"
METRIC_LLM_TOTAL = "otc_agent_llm_total"


def emit_node_completed(node: str, status: str = "ok", elapsed_ms: int | None = None) -> None:
    """节点完成时 emit。status: ok / error"""
    coll = get_collector()
    coll.inc_counter(METRIC_NODE_TOTAL, {"node": node, "status": status})
    if elapsed_ms is not None:
        coll.observe_histogram(
            METRIC_INTENT_LATENCY,
            elapsed_ms,
            {"product_type": "unknown", "intent": "unknown", "node": node},
        )


def emit_intent_latency(product_type: str, intent: str, elapsed_ms: int) -> None:
    """整条请求处理完，按 product_type × intent 维度记延迟。"""
    get_collector().observe_histogram(
        METRIC_INTENT_LATENCY,
        elapsed_ms,
        {"product_type": product_type, "intent": intent},
    )


def emit_fallback(reason: str = "unknown") -> None:
    """fallback render 触发。reason: cascade_fail / zero_match / hitl_card / error_fallback"""
    get_collector().inc_counter(METRIC_FALLBACK_TOTAL, {"reason": reason})


def emit_hitl(node: str) -> None:
    """HITL interrupt 触发。"""
    get_collector().inc_counter(METRIC_HITL_TOTAL, {"node": node})


def emit_llm_call(model: str, status: str) -> None:
    """LLM 调用结束。status: ok / error / timeout"""
    get_collector().inc_counter(METRIC_LLM_TOTAL, {"model": model, "status": status})


# ============================================================
# 计时上下文（用于细粒度延迟测量）
# ============================================================


class Timer:
    """with Timer() as t: ... ; t.elapsed_ms  → int

    用法:
        with Timer() as t:
            do_work()
        emit_intent_latency("swap", "place_order", t.elapsed_ms)
    """

    def __init__(self) -> None:
        self._start: float = 0.0
        self.elapsed_ms: int = 0

    def __enter__(self) -> "Timer":
        self._start = perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.elapsed_ms = int((perf_counter() - self._start) * 1000)


__all__ = [
    "MetricsCollector",
    "Timer",
    "emit_node_completed",
    "emit_intent_latency",
    "emit_fallback",
    "emit_hitl",
    "emit_llm_call",
    "get_collector",
    "METRIC_NODE_TOTAL",
    "METRIC_INTENT_LATENCY",
    "METRIC_FALLBACK_TOTAL",
    "METRIC_HITL_TOTAL",
    "METRIC_LLM_TOTAL",
]
