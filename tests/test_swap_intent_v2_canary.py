"""swap.intent v2 灰度生效验证（5% canary · 修 g008）。

不调真 LLM，只验证：
1. _versions.yaml 配置生效 → resolve_prompt_version 返回的 name 在 v1/v2 间分布
2. 5% 灰度比例与 yaml 权重一致（±5% 浮动）
3. v2 文件实际可加载（intent_v2.md 存在 + system 段已修改）
4. g008 raw_content 命中 v2 路由时，trace 记 prompt=intent_v2

真 LLM 评估留给业务方拨测 / shadow 阶段（pytest 不调外部 LLM）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.prompts import clear_cache, load_prompt, resolve_prompt_version
from app.subgraphs.swap import build_swap_graph
from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap.models import SwapIntentOutput


@pytest.fixture(autouse=True)
def _clear() -> None:
    clear_cache()
    yield
    clear_cache()


# ============================================================
# 1. _versions.yaml 5% 灰度生效
# ============================================================


def test_versions_yaml_routes_5pct_to_v2() -> None:
    """1000 个不同 conversation_id 抽样：v2 占比 ≈ 5% (±2%)。"""
    counts = {"intent": 0, "intent_v2": 0}
    for i in range(1000):
        name = resolve_prompt_version("swap", "intent", f"conv-{i}")
        counts.setdefault(name, 0)
        counts[name] += 1

    total = counts["intent"] + counts["intent_v2"]
    assert total == 1000, counts
    v2_ratio = counts["intent_v2"] / total
    assert 0.03 <= v2_ratio <= 0.07, f"v2_ratio={v2_ratio}, counts={counts}"


def test_versions_yaml_route_stable_per_conversation() -> None:
    """同一 conversation_id 永远命中同一版本。"""
    cid = "stable-conv-g008"
    first = resolve_prompt_version("swap", "intent", cid)
    for _ in range(50):
        assert resolve_prompt_version("swap", "intent", cid) == first


# ============================================================
# 2. v2 文件实际加载 + 关键修复内容存在
# ============================================================


def test_intent_v2_loads_with_g008_fix_marker() -> None:
    """intent_v2.md 文件存在，且包含 g008 修复关键标识。"""
    p_v1 = load_prompt("swap", "intent")
    p_v2 = load_prompt("swap", "intent_v2")

    # v2 不为空且与 v1 明显不同
    assert p_v2.system
    assert p_v2.system != p_v1.system
    # 含 g008 修复标识词
    assert "g008" in p_v2.system or "确认修改" in p_v2.system
    # v2 应保留 v1 大部分原文（仅追加规则，不大幅改写）
    assert len(p_v2.system) > len(p_v1.system) * 0.95


# ============================================================
# 3. swap_intent 节点接入 v2 后 trace 记录正确版本
# ============================================================


@pytest.mark.asyncio
async def test_swap_intent_records_prompt_name_in_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """swap.intent 写 trace 含 prompt_name（含 v1 / v2 后缀）。"""
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(
        return_value=SwapIntentOutput(type="confirm_modify_order")
    )
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_base)

    # 强制 env override 走 v2
    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "v2")
    clear_cache()

    graph = build_swap_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "swap确认修改订单 H-20260304-ABCD12345678",
            "conversation_id": "g008-canary",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )

    intent_entry = next(
        e for e in final["trace"] if e.node == "swap_intent"
    )
    assert "prompt=intent_v2" in intent_entry.decision
    assert intent_entry.llm_output["prompt_name"] == "intent_v2"
    assert final["intent"] == "confirm_modify_order"


@pytest.mark.asyncio
async def test_swap_intent_v1_also_records_prompt_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 强制 v1 时 trace 也记 prompt=intent（无后缀，标识 v1）。"""
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(
        return_value=SwapIntentOutput(type="place_order_request")
    )
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_base)

    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "v1")
    clear_cache()

    graph = build_swap_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "互换下单",
            "conversation_id": "v1-control",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )

    intent_entry = next(
        e for e in final["trace"] if e.node == "swap_intent"
    )
    assert "prompt=intent" in intent_entry.decision
    assert intent_entry.llm_output["prompt_name"] == "intent"
