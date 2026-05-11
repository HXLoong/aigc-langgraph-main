"""端到端集成测试：Mock 掉 LLM 和后端 HTTP，跑完整的主图。

目的：
1. 证明图拓扑正确（无死锁、无断边、无递归超限）
2. 证明 State reducer 正常工作
3. 证明每个产品类型都能走通对应子图
4. 证明 checkpoint 机制工作（用 InMemorySaver 替代 MySQL）

不依赖真实的 LLM 或后端服务，CI 里可以直接跑。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("langgraph.graph")
pytest.importorskip("langgraph.checkpoint.memory")


@pytest.fixture
def mock_settings(monkeypatch):
    """最小化配置，避开真实环境变量。"""
    env = {
        "CHECKPOINT_MYSQL_URI": "mysql://test:test@localhost:3306/test",
        "BUSINESS_MYSQL_URI": "mysql+aiomysql://test:test@localhost:3306/test",
        "QWEN_API_BASE": "http://mock/v1",
        "QWEN_API_KEY": "mock",
        "OTC_API_BASE_URL": "http://mock",
        "OTC_API_SECRET": "mock-secret",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # 清 lru_cache
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_backend(monkeypatch):
    """Mock OtcBackendClient 的所有方法。

    Python mock 陷阱：必须 patch "where it's looked up"（即所有 import 它的地方），
    而不是 patch 定义它的原模块。
    """
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.swap_operate = AsyncMock(return_value={
        "code": 0, "result": "互换订单已创建",
    })
    mock_client.option_operate = AsyncMock(return_value={
        "code": 0, "result": "期权订单已创建",
    })
    mock_client.financial_orders_operate = AsyncMock(return_value={
        "code": 0, "result": "平仓操作成功",
    })
    mock_client.query_close_orders = AsyncMock(return_value=[
        {"orderId": "CO-20260304-4FE9C941",
         "contractCode": "OPT-CO20260304-4FE9C941",
         "notional": 10_000_000, "availableNotional": 10_000_000,
         "underlyingCode": "000155.SZ", "underlyingName": "川能动力",
         "optionType": "欧式看涨", "createTime": "2026-03-04 10:00"},
    ])
    mock_client.bot_name_list = AsyncMock(return_value=["机器人A"])
    mock_client.conversation_orders = AsyncMock(return_value=[])
    mock_client.counterparty_list = AsyncMock(return_value=[
        {"id": 1, "shortName": "对手A"},
    ])
    mock_client.set_intent = AsyncMock()

    def factory(*args, **kwargs):
        return mock_client

    # patch 所有使用点
    for target in (
        "app.tools.otc_backend.OtcBackendClient",
        "app.subgraphs.swap.OtcBackendClient",
        "app.subgraphs.option.OtcBackendClient",
        "app.subgraphs.close.OtcBackendClient",
    ):
        monkeypatch.setattr(target, factory)
    return mock_client


@pytest.mark.asyncio
async def test_e2e_unknown_intent(mock_settings, mock_backend):
    """兜底路径：没有匹配任何关键词 → unknown → render_reply。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.graphs.main_graph import build_main_graph
    from app.state import make_initial_state

    cp = InMemorySaver()
    graph = build_main_graph(cp)

    state = make_initial_state({
        "conversation_id": "c-unknown",
        "message_id": "m-unknown",
        "room_id": "r", "user_id": "u", "guid": "",
        "raw_content": "你好，今天天气真好",
    })
    state["at_bot"] = True
    config = {"configurable": {"thread_id": "c-unknown"}}
    result = await graph.ainvoke(state, config=config)

    assert result["product_type"] == "unknown"
    assert result.get("reply_text") is not None
    assert "未识别" in result["reply_text"]


@pytest.mark.asyncio
async def test_e2e_option_close_by_order_number(mock_settings, mock_backend):
    """平仓路径：命中 CO- 单号 → option_close 子图。"""
    from langgraph.checkpoint.memory import InMemorySaver

    # close 子图同时用 get_qwen_standard (classify/extract_holding/extract_order)
    # 和 get_qwen_structured (extract_close_place)，两边的 with_structured_output
    # 共用同一个 side_effect 分流逻辑。
    with patch("app.llm.clients.get_qwen_standard") as mock_std, \
         patch("app.llm.clients.get_qwen_structured") as mock_struct:

        from app.subgraphs.close_models import (
            CloseIntentOutput,
            ClosePlaceOrderLeg,
            ClosePlaceOrderOutput,
        )

        def _make_llm_for(model_cls):
            mock_llm = MagicMock()
            if model_cls is CloseIntentOutput:
                mock_llm.ainvoke = AsyncMock(
                    return_value=CloseIntentOutput(type="close_order_request")
                )
            elif model_cls is ClosePlaceOrderOutput:
                mock_llm.ainvoke = AsyncMock(return_value=ClosePlaceOrderOutput(
                    close_order_list=[
                        ClosePlaceOrderLeg(
                            internal_trade_id="CO-20260304-4FE9C941",
                            price_type="market",
                            full_close=True,
                        )
                    ],
                ))
            else:
                # 其他模型（CloseHoldingQueryOutput, CloseOrderNoListOutput）用默认空值
                mock_llm.ainvoke = AsyncMock(return_value=model_cls())
            return mock_llm

        mock_std.return_value.with_structured_output.side_effect = _make_llm_for
        mock_struct.return_value.with_structured_output.side_effect = _make_llm_for

        from app.graphs.main_graph import build_main_graph
        from app.state import make_initial_state

        cp = InMemorySaver()
        graph = build_main_graph(cp)

        state = make_initial_state({
            "conversation_id": "c-close",
            "message_id": "m-close",
            "room_id": "r", "user_id": "u", "guid": "",
            "raw_content": "请平 CO-20260304-4FE9C941 全部",
        })
        state["at_bot"] = True
        config = {"configurable": {"thread_id": "c-close"}}
        result = await graph.ainvoke(state, config=config)

        assert result["product_type"] == "option_close"
        assert result["intent"] == "close_order_request"
        assert result["api_code"] == 0
        # 平仓确认应包含申请详情和确认引导
        assert "平仓申请" in result.get("api_result", "")
        assert "确认平仓" in result.get("api_result", "")


@pytest.mark.asyncio
async def test_e2e_checkpoint_resume(mock_settings, mock_backend):
    """Checkpoint 机制验证：同一 thread_id 的 state 可以被检索。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.graphs.main_graph import build_main_graph
    from app.state import make_initial_state

    cp = InMemorySaver()
    graph = build_main_graph(cp)

    state = make_initial_state({
        "conversation_id": "c-resume",
        "message_id": "m1",
        "room_id": "r", "user_id": "u", "guid": "",
        "raw_content": "你好",
    })
    config = {"configurable": {"thread_id": "c-resume"}}
    await graph.ainvoke(state, config=config)

    # 从 checkpoint 读回 state
    snapshot = await graph.aget_state(config)
    assert snapshot is not None
    assert snapshot.values["wechat_input"]["conversation_id"] == "c-resume"
    assert "trace" in snapshot.values
    assert len(snapshot.values["trace"]) > 0


@pytest.mark.asyncio
async def test_e2e_trace_accumulation(mock_settings, mock_backend):
    """每个节点都应追加一条 trace。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.graphs.main_graph import build_main_graph
    from app.state import make_initial_state

    cp = InMemorySaver()
    graph = build_main_graph(cp)

    state = make_initial_state({
        "conversation_id": "c-trace",
        "message_id": "m-trace",
        "room_id": "r", "user_id": "u", "guid": "",
        "raw_content": "xyz 无意义",
    })
    config = {"configurable": {"thread_id": "c-trace"}}
    result = await graph.ainvoke(state, config=config)

    # 路径：ingest → route_product → render_reply
    trace_nodes = [t["node"] for t in result["trace"]]
    assert "ingest" in trace_nodes
    assert "route_product" in trace_nodes
    assert "render_reply" in trace_nodes


@pytest.mark.asyncio
async def test_e2e_parse_excel_row_extraction(mock_settings):
    """Excel 解析的单元测试，不走图。"""
    import io
    from unittest.mock import patch as _patch

    try:
        import openpyxl
    except ImportError:
        pytest.skip("openpyxl 未安装")

    from app.state import make_initial_state
    from app.subgraphs.swap import parse_excel

    # 构造一个内存 Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["证券名称", "证券代码", "买入数量", "产品"])
    ws.append(["贵州茅台", "600519.SH", 1000, "小明账户"])
    ws.append(["五粮液", "000858.SZ", 2000, "小明账户"])
    buf = io.BytesIO()
    wb.save(buf)
    excel_bytes = buf.getvalue()

    state = make_initial_state({
        "conversation_id": "c", "message_id": "m",
        "room_id": "r", "user_id": "u", "guid": "",
        "raw_content": "请按附件下单",
        "attachments": [{"url": "http://mock/test.xlsx", "type": "excel"}],
    })

    # Mock httpx 下载
    mock_response = MagicMock()
    mock_response.content = excel_bytes
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)

    with _patch("httpx.AsyncClient", return_value=mock_client):
        result = await parse_excel(state)

    assert "wechat_input" in result
    new_raw = result["wechat_input"]["raw_content"]
    assert "600519.SH" in new_raw
    assert "000858.SZ" in new_raw
    # 列名归一化：产品 → 交易对手
    assert "交易对手=小明账户" in new_raw
