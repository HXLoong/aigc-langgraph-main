"""提示词加载器 + 历史消息加载的测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ============================================================
# 提示词加载器
# ============================================================
def test_load_swap_intent_prompt():
    from app.prompts import load_prompt

    p = load_prompt("swap", "intent")
    assert p.name == "swap/intent"
    assert "互换" in p.system or "Swap" in p.system
    assert len(p.system) > 1000   # 真实 Dify 提示词应该很长


def test_load_swap_place_order_prompt():
    """这是最大的一个提示词，应该能成功加载。"""
    from app.prompts import load_prompt

    p = load_prompt("swap", "place_order")
    assert len(p.system) > 10000


# ============================================================
# compose_prompt：v2 版本化拼装
# ============================================================
def test_compose_prompt_v1_equivalent_to_load_prompt():
    """v1 版本走 load_prompt，行为完全等价。"""
    from app.prompts import compose_prompt, load_prompt

    v1_direct = load_prompt("swap", "place_order")
    v1_compose = compose_prompt("swap", "place_order", version="v1")
    assert v1_compose.system == v1_direct.system


def test_compose_prompt_v2_merges_base_and_leaf():
    """v2 版本拼接 _base.md + place_order.md，总长小于 v1。"""
    from app.prompts import compose_prompt, load_prompt

    v1 = load_prompt("swap", "place_order")
    v2 = compose_prompt("swap", "place_order", version="v2")

    # v2 明显短（预期 22% 左右裁剪）
    assert len(v2.system) < len(v1.system)
    assert len(v2.system) < len(v1.system) * 0.85

    # v2 应含 base 里的字段规则 + 叶子里的示例关键词
    base = load_prompt("swap/v2", "_base")
    leaf = load_prompt("swap/v2", "place_order")
    assert base.system in v2.system
    assert leaf.system in v2.system


def test_compose_prompt_v2_place_order_example_retained():
    """v2 的 place_order 片段保留了三个代表性示例关键词。"""
    from app.prompts import compose_prompt

    v2 = compose_prompt("swap", "place_order", version="v2")
    # 三个保留示例的特征词
    assert "POV25" in v2.system         # 示例 1) POV 基础
    assert "09:30" in v2.system          # 示例 5) TWAP 时间窗
    assert "中国平安" in v2.system        # 示例 7.1) 排除法
    # 示例段专有的标识不应出现（被裁掉的示例编号）
    assert "5.1)请求下单" not in v2.system
    assert "9.1)请求下单" not in v2.system
    assert "6.1)请求下单" not in v2.system


def test_load_swap_confirm_order_has_orderid_rules():
    from app.prompts import load_prompt

    p = load_prompt("swap", "confirm_order")
    # 原始 Dify 提示词应包含订单 ID 格式规则
    assert "H-" in p.system
    assert "orderId" in p.system or "订单" in p.system


def test_load_close_intent_prompt():
    from app.prompts import load_prompt

    p = load_prompt("option_close", "intent")
    assert "close_order_query" in p.system
    assert "close_order_request" in p.system


def test_load_ticker_prompts_all_exist():
    """确认 ticker 目录下所有关键提示词都存在。"""
    from app.prompts import load_prompt

    for name in ("infer_code", "completeness", "tokenize", "rank"):
        p = load_prompt("ticker", name)
        assert len(p.system) > 100


def test_load_prompt_file_not_found():
    from app.prompts import load_prompt

    with pytest.raises(FileNotFoundError):
        load_prompt("swap", "not_exists_xyz")


def test_load_prompt_unknown_category():
    from app.prompts import load_prompt

    with pytest.raises(FileNotFoundError):
        load_prompt("unknown_category", "intent")


def test_prompt_render_user_simple():
    """render_user 替换 {{variable}} 占位符。"""
    from app.prompts import Prompt

    p = Prompt(
        name="test",
        system="sys",
        user_template="Hello {{name}}, you are {{age}} years old",
    )
    assert p.render_user(name="Alice", age="30") == \
        "Hello Alice, you are 30 years old"


def test_prompt_render_user_missing_var_stays():
    """未提供的占位符保持原样（Dify 兼容性）。"""
    from app.prompts import Prompt

    p = Prompt(
        name="test",
        system="sys",
        user_template="{{provided}} {{#dify.style#}}",
    )
    result = p.render_user(provided="OK")
    assert "OK" in result
    assert "{{#dify.style#}}" in result   # Dify 占位符保留


def test_parse_prompt_md_format():
    """内部解析函数的正确性：能分辨 [system] 和 [user] 段。"""
    from app.prompts import _parse_prompt_md

    md = """# 测试

- **node_id**: `123`

## [system]

```
我是 system 提示词
有多行
```

## [user]

```
我是 user 模板：{{name}}
```
"""
    system, user = _parse_prompt_md(md)
    assert system == "我是 system 提示词\n有多行"
    assert user == "我是 user 模板：{{name}}"


# ============================================================
# 历史消息加载
# ============================================================
@pytest.mark.asyncio
async def test_load_history_from_empty_checkpoint():
    """空 checkpoint 应返回空列表。"""
    from app.nodes.history import load_history_from_checkpoint

    mock_graph = MagicMock()

    async def empty_iter(*args, **kwargs):
        for _ in ():
            yield

    mock_graph.aget_state_history = empty_iter

    result = await load_history_from_checkpoint(mock_graph, "test-conv")
    assert result == []


@pytest.mark.asyncio
async def test_load_history_handles_exception():
    """aget_state_history 抛异常时应返回空列表，而非崩溃。"""
    from app.nodes.history import load_history_from_checkpoint

    mock_graph = MagicMock()
    mock_graph.aget_state_history = MagicMock(side_effect=RuntimeError("boom"))

    result = await load_history_from_checkpoint(mock_graph, "test-conv")
    assert result == []


@pytest.mark.asyncio
async def test_load_history_with_snapshots():
    """正常情况：多个 snapshot 被展开成 user+assistant 消息对。"""
    from app.nodes.history import load_history_from_checkpoint

    # 构造 mock snapshots
    snap1 = MagicMock()
    snap1.values = {
        "wechat_input": {"raw_content": "你好", "message_id": "m1"},
        "api_result": "您好，有什么可以帮您",
        "product_type": "unknown",
    }
    snap2 = MagicMock()
    snap2.values = {
        "wechat_input": {"raw_content": "下单茅台 100 手", "message_id": "m2"},
        "api_result": "订单已创建",
        "product_type": "swap",
        "intent": "place_order_request",
    }

    async def iter_fn(*args, **kwargs):
        yield snap2   # 最新的在前
        yield snap1

    mock_graph = MagicMock()
    mock_graph.aget_state_history = iter_fn

    result = await load_history_from_checkpoint(
        mock_graph, "test-conv", max_turns=5
    )

    # 应有 4 条：2 轮 × (user+assistant)
    assert len(result) == 4
    # 且时间顺序：旧的在前
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "你好"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "user"
    assert result[2]["content"] == "下单茅台 100 手"


def test_format_history_for_prompt_empty():
    from app.nodes.history import format_history_for_prompt

    assert format_history_for_prompt([]) == "(无历史)"


def test_format_history_for_prompt_truncates():
    from app.nodes.history import format_history_for_prompt

    # 每条 50 字符，累加超过 max_chars 就截
    msgs = [
        {"role": "user", "content": "A" * 50},
        {"role": "assistant", "content": "B" * 50},
        {"role": "user", "content": "C" * 50},
    ]
    result = format_history_for_prompt(msgs, max_chars=80)
    # 应包含至少第一条
    assert "[user]" in result
    # 受 max_chars 约束，不会三条全出
    assert len(result) < 200


def test_format_history_content_truncation():
    """单条消息的 content 会被截断到 500 字符。"""
    from app.nodes.history import format_history_for_prompt

    msgs = [{"role": "user", "content": "X" * 2000}]
    result = format_history_for_prompt(msgs)
    # 单条内容会截到 500 字符
    assert "X" * 500 in result
    # 不应包含 2000 个 X（被截断了）
    assert "X" * 501 not in result
