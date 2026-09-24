"""金丝雀切流监控基础设施。

按 CONTEXT.md 定义，金丝雀切流是**按群组**：客户侧 Java 配置管理员把指定群的
`agentUrl` 从 Dify 改到 LangGraph。LangGraph 服务侧不做流量分配 —— 只观察哪些 roomId
实际进了进程，对照 allowlist 检查是否有误切。

核心场景：
- 灰度第一阶段：1-2 个测试群进 LangGraph，其余继续 Dify
- 若误把非测试群的 `agentUrl` 切到 LangGraph，**生产流量会泄漏过来**
- 此时应立即告警并回切 `agentUrl`（步骤见 on-call runbook §7）

配置加载顺序：
1. 环境变量 `CANARY_ROOM_IDS`（逗号分隔的 roomId 列表）
2. 若未设置 → 空集合（金丝雀未启用，任何 roomId 都算非 canary）

注意：
- allowlist 是 **白名单**，不在表内的 roomId 视为"非 canary 流量"
- 全量切换时应把 CANARY_ROOM_IDS 设为 `ALL`，表示全量上线（清空则所有流量都算非 canary）
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


# `ALL` 是全量切换标记，表示所有 roomId 都视为 canary
_ALL_MARKER = "ALL"


def _load_canary_room_ids() -> frozenset[str]:
    """从 CANARY_ROOM_IDS 环境变量加载白名单。

    格式：逗号分隔，如 `r-test-1,r-test-2`
    特殊值 `ALL` → 全量上线，任何 roomId 都返回 True
    """
    raw = os.environ.get("CANARY_ROOM_IDS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(token.strip() for token in raw.split(",") if token.strip())


# 进程启动时加载一次（金丝雀切换不需要热更，调整切流群时同步更新 .env 并重启服务）
_CANARY_ROOM_IDS: frozenset[str] = _load_canary_room_ids()


def is_canary_room(room_id: str | None) -> bool:
    """判定 roomId 是否在金丝雀白名单。

    Args:
        room_id: state 中的 roomId（企微群 ID）

    Returns:
        True 表示该群在金丝雀名单内 / 全量阶段（ALL），False 表示非 canary。
        None / 空串 → False（无 room_id 不算 canary）。
    """
    if not room_id:
        return False
    if _ALL_MARKER in _CANARY_ROOM_IDS:
        return True
    return room_id in _CANARY_ROOM_IDS


def get_canary_room_ids() -> frozenset[str]:
    """暴露当前 allowlist 供监控 / 调试用。"""
    return _CANARY_ROOM_IDS


def reload_canary_room_ids() -> frozenset[str]:
    """重新加载白名单（测试用 / 运维热更）。"""
    global _CANARY_ROOM_IDS
    _CANARY_ROOM_IDS = _load_canary_room_ids()
    logger.info(
        "canary roomId allowlist reloaded: %d entries (ALL=%s)",
        len(_CANARY_ROOM_IDS),
        _ALL_MARKER in _CANARY_ROOM_IDS,
    )
    return _CANARY_ROOM_IDS


__all__ = [
    "is_canary_room",
    "get_canary_room_ids",
    "reload_canary_room_ids",
]
