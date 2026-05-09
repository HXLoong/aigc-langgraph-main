"""期权子图全量测试。

每个测试用 INPUT / OUTPUT 注释标明出入参，不读代码也能知道测什么。
运行 `pytest -s tests/test_option.py -v` 查看详情。

Mock 要点：
- get_qwen_thinking 是函数内延迟导入 → patch 在 app.subgraphs.option
- OtcBackendClient 是模块级导入 → patch 在 app.subgraphs.option
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("langgraph.graph")
pytest.importorskip("langgraph.checkpoint.memory")

from app.state import AgentState, TickerCandidate, make_initial_state
from app.subgraphs.option_models import (
    OptionExtractOutput,
    OptionOrderLeg,
    OptionParamLimit,
)


# ============================================================
# 输出辅助
# ============================================================
def _show(name: str, inputs: dict, outputs: dict):
    lines = [f"\n{'='*60}", f"  {name}", f"{'='*60}", "  INPUT:"]
    for k, v in inputs.items():
        lines.append(f"    {k} = {_fmt(v)}")
    lines.append("  OUTPUT:")
    for k, v in outputs.items():
        lines.append(f"    {k} = {_fmt(v)}")
    lines.append(f"{'='*60}")
    print("\n".join(lines))


def _fmt(v, max_len=300):
    s = repr(v)
    return s[:max_len] + "..." if len(s) > max_len else s


def _make_state(raw_content: str, **overrides) -> AgentState:
    s = make_initial_state({
        "conversation_id": "c1", "message_id": "m1",
        "room_id": "r", "user_id": "u", "guid": "",
        "raw_content": raw_content,
    })
    s.update(overrides)
    return s


# ============================================================
# Mock 工厂
# ============================================================
def _mock_backend_client(code: int = 0, result: str = "ok"):
    """Mock OtcBackendClient，返回指定 code 和 result。"""
    mock_resp = {"code": code, "result": result}
    mock_client = MagicMock()
    mock_client.financial_orders_operate = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _mock_llm_extract(*, type_: str = "new_inquiry", operate: str = "inquiry",
                      order_list: list | None = None):
    """Mock extract_option 的 LLM 输出。"""
    if order_list is None:
        order_list = []
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=OptionExtractOutput(
        type=type_,  # type: ignore[arg-type]
        operate=operate,
        order_list=order_list,
    ))
    return llm


# ============================================================
# 一、路由函数 route_quick_query
# ============================================================
class TestRouteQuickQuery:

    def test_fast_query_true_returns_yes(self):
        """快速询价标记为真 → "yes"
        INPUT:  state.fast_query = True
        OUTPUT: "yes"
        """
        from app.subgraphs.option import route_quick_query
        result = route_quick_query({"fast_query": True})
        _show("快速询价 → yes", {"fast_query": True}, {"route": result})
        assert result == "yes"

    def test_fast_query_false_returns_no(self):
        """快速询价标记为假 → "no"
        INPUT:  state.fast_query = False（或缺失）
        OUTPUT: "no"
        """
        from app.subgraphs.option import route_quick_query
        result = route_quick_query({})
        _show("非快速询价 → no", {"fast_query": False}, {"route": result})
        assert result == "no"


# ============================================================
# 二、detect_quick_query（纯正则，不 Mock）
# ============================================================
class TestDetectQuickQuery:

    @pytest.mark.asyncio
    async def test_keyword_can_see_up(self):
        """命中"参与型看涨"
        INPUT:  raw_content = "参与型看涨 腾讯控股 1个月"
        OUTPUT: fast_query = True, trace decision = "quick"
        """
        from app.subgraphs.option import detect_quick_query
        state = _make_state("参与型看涨 腾讯控股 1个月")
        result = await detect_quick_query(state)
        _show("参与型看涨 → quick",
              {"raw_content": state["wechat_input"]["raw_content"]},
              {"fast_query": result["fast_query"],
               "decision": result["trace"][0]["decision"]})
        assert result["fast_query"] is True
        assert result["trace"][0]["decision"] == "quick"

    @pytest.mark.asyncio
    async def test_keyword_can_see_put(self):
        """命中"参与型看跌"
        INPUT:  raw_content = "参与型看跌 腾讯控股 3M"
        OUTPUT: fast_query = True
        """
        from app.subgraphs.option import detect_quick_query
        state = _make_state("参与型看跌 腾讯控股 3M")
        result = await detect_quick_query(state)
        _show("参与型看跌 → quick",
              {"raw_content": state["wechat_input"]["raw_content"]},
              {"fast_query": result["fast_query"]})
        assert result["fast_query"] is True

    @pytest.mark.asyncio
    async def test_keyword_snowball(self):
        """命中"雪球"
        INPUT:  raw_content = "雪球询价 腾讯控股"
        OUTPUT: fast_query = True
        """
        from app.subgraphs.option import detect_quick_query
        state = _make_state("雪球询价 腾讯控股")
        result = await detect_quick_query(state)
        _show("雪球 → quick",
              {"raw_content": state["wechat_input"]["raw_content"]},
              {"fast_query": result["fast_query"]})
        assert result["fast_query"] is True

    @pytest.mark.asyncio
    async def test_no_keyword_goes_standard(self):
        """不含快速询价关键词 → 标准路径
        INPUT:  raw_content = "期权询价 腾讯控股 欧式看涨 行权价500"
        OUTPUT: fast_query = False, trace decision = "standard"
        """
        from app.subgraphs.option import detect_quick_query
        state = _make_state("期权询价 腾讯控股 欧式看涨 行权价500")
        result = await detect_quick_query(state)
        _show("无快速关键词 → standard",
              {"raw_content": state["wechat_input"]["raw_content"]},
              {"fast_query": result["fast_query"],
               "decision": result["trace"][0]["decision"]})
        assert result["fast_query"] is False
        assert result["trace"][0]["decision"] == "standard"

    @pytest.mark.asyncio
    async def test_empty_message(self):
        """空消息
        INPUT:  raw_content = ""
        OUTPUT: fast_query = False
        """
        from app.subgraphs.option import detect_quick_query
        state = _make_state("")
        result = await detect_quick_query(state)
        _show("空消息 → standard",
              {"raw_content": ""},
              {"fast_query": result["fast_query"]})
        assert result["fast_query"] is False


# ============================================================
# 三、fast_query_api（Mock OtcBackendClient）
# ============================================================
class TestFastQueryApi:

    @pytest.mark.asyncio
    async def test_normal_fast_query(self):
        """快速询价正常返回
        INPUT:  raw_content = "参与型看涨 腾讯控股 1个月"
               backend 返回 code=0
        OUTPUT: api_code=0, intent="new_inquiry"
        """
        from app.subgraphs.option import fast_query_api

        mock_client = _mock_backend_client(code=0, result="询价已受理")
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            result = await fast_query_api(_make_state("参与型看涨 腾讯控股 1个月"))

        _show("fast_query_api 正常",
              {"raw_content": "参与型看涨 腾讯控股 1个月"},
              {"api_code": result["api_code"], "intent": result["intent"],
               "api_result": result["api_result"]})
        assert result["api_code"] == 0
        assert result["intent"] == "new_inquiry"

    @pytest.mark.asyncio
    async def test_backend_error(self):
        """后端返回业务错误
        INPUT:  backend 返回 code=400
        OUTPUT: api_code=400, intent 仍然为 "new_inquiry"
        """
        from app.subgraphs.option import fast_query_api

        mock_client = _mock_backend_client(code=400, result="参数错误")
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            result = await fast_query_api(_make_state("雪球询价 腾讯"))

        _show("fast_query_api 后端错误",
              {"raw_content": "雪球询价 腾讯"},
              {"api_code": result["api_code"], "intent": result["intent"]})
        assert result["api_code"] == 400

    @pytest.mark.asyncio
    async def test_network_error_caught_by_safe_node(self):
        """网络异常 → @safe_node 兜底
        INPUT:  OtcBackendClient.__aenter__ 抛 ConnectionError
        OUTPUT: trace 中有 status="error"
        """
        from app.subgraphs.option import fast_query_api

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(side_effect=ConnectionError("拒绝连接"))
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            result = await fast_query_api(_make_state("参与型看涨 腾讯"))

        _show("fast_query_api 网络异常",
              {"error": "ConnectionError"},
              {"error": result.get("error", ""),
               "trace_status": [t.get("status") for t in result.get("trace", [])]})
        assert any(t.get("status") == "error" for t in result.get("trace", []))


# ============================================================
# 四、extract_option（Mock LLM）
# ============================================================
class TestExtractOption:

    @pytest.mark.asyncio
    async def test_new_inquiry(self):
        """新询价意图
        INPUT:  raw_content = "期权询价 腾讯控股 欧式看涨 行权价500 1M"
               resolved_tickers = [600519.SH]
               LLM 返回 type="new_inquiry", operate="inquiry"
        OUTPUT: intent="new_inquiry", operate="inquiry"
        """
        from app.subgraphs.option import extract_option

        state = _make_state(
            "期权询价 腾讯控股 欧式看涨 行权价500 1M",
            resolved_tickers=[TickerCandidate(keyword="腾讯", wind_code="600519.SH")],
        )
        mock_llm = _mock_llm_extract(type_="new_inquiry", operate="inquiry", order_list=[
            OptionOrderLeg(stock_code="600519.SH", stock_name="腾讯控股",
                          option_type="欧式看涨", strike_price=500.0, tenor="1M"),
        ])
        with patch("app.llm.clients.get_qwen_thinking") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await extract_option(state)

        _show("extract_option new_inquiry",
              {"raw_content": "期权询价 腾讯控股 欧式看涨 行权价500 1M",
               "resolved_tickers": ["600519.SH"]},
              {"intent": result["intent"], "operate": result["operate"],
               "order_count": len(result["order_list"])})
        assert result["intent"] == "new_inquiry"
        assert result["operate"] == "inquiry"
        assert len(result["order_list"]) == 1

    @pytest.mark.asyncio
    async def test_place_order(self):
        """下单意图
        INPUT:  LLM 返回 type="place_order", operate="new_order"
        OUTPUT: intent="place_order"
        """
        from app.subgraphs.option import extract_option

        state = _make_state("期权下单 腾讯控股",
                          resolved_tickers=[TickerCandidate(keyword="腾讯", wind_code="600519.SH")])
        mock_llm = _mock_llm_extract(type_="place_order", operate="new_order")
        with patch("app.llm.clients.get_qwen_thinking") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await extract_option(state)

        _show("extract_option place_order",
              {"raw_content": "期权下单 腾讯控股"},
              {"intent": result["intent"], "operate": result["operate"]})
        assert result["intent"] == "place_order"
        assert result["operate"] == "new_order"

    @pytest.mark.asyncio
    async def test_all_intent_types(self):
        """遍历全部 7 种意图
        INPUT:  LLM 依次返回 7 种 OptionIntentType
        OUTPUT: 全部正确透传
        """
        from app.subgraphs.option import extract_option

        intents = [
            ("new_inquiry", "inquiry"),
            ("existing_command", "modify"),
            ("place_order", "new_order"),
            ("modify_order", "modify_order"),
            ("cancel_order", "cancel_order"),
            ("confirm", "confirm"),
            ("unknown", ""),
        ]
        for intent, operate in intents:
            state = _make_state("期权操作",
                              resolved_tickers=[TickerCandidate(keyword="x", wind_code="000001.SZ")])
            mock_llm = _mock_llm_extract(type_=intent, operate=operate)
            with patch("app.llm.clients.get_qwen_thinking") as m:
                m.return_value.with_structured_output.return_value = mock_llm
                result = await extract_option(state)
            assert result["intent"] == intent, f"{intent} mismatch"
            assert result["operate"] == operate, f"{operate} mismatch"
        _show("extract_option 7种意图",
              {"intents": [i[0] for i in intents]},
              {"result": "全部通过"})

    @pytest.mark.asyncio
    async def test_empty_tickers(self):
        """无已解析标的
        INPUT:  resolved_tickers = []
               LLM 返回 type="new_inquiry", order_list=[]
        OUTPUT: intent="new_inquiry", order_list 为空
        """
        from app.subgraphs.option import extract_option

        state = _make_state("期权询价", resolved_tickers=[])
        mock_llm = _mock_llm_extract(type_="new_inquiry", operate="inquiry")
        with patch("app.llm.clients.get_qwen_thinking") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await extract_option(state)

        _show("extract_option 空tickers",
              {"resolved_tickers": []},
              {"intent": result["intent"]})
        assert result["intent"] == "new_inquiry"

    @pytest.mark.asyncio
    async def test_with_history(self):
        """带历史消息
        INPUT:  history_messages = [{role:"user", content:"之前询价过"}]
        OUTPUT: intent 正常解析
        """
        from app.subgraphs.option import extract_option

        state = _make_state(
            "改一下行权价到600",
            history_messages=[{"role": "user", "content": "之前询价过"}],
            resolved_tickers=[TickerCandidate(keyword="腾讯", wind_code="600519.SH")],
        )
        mock_llm = _mock_llm_extract(type_="modify_order", operate="modify_order")
        with patch("app.llm.clients.get_qwen_thinking") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await extract_option(state)

        _show("extract_option 带历史",
              {"raw_content": "改一下行权价到600",
               "history": "有1条"},
              {"intent": result["intent"]})
        assert result["intent"] == "modify_order"

    @pytest.mark.asyncio
    async def test_llm_error_caught_by_safe_node(self):
        """LLM 抛异常 → @safe_node 兜底
        INPUT:  LLM 抛出 RuntimeError("超时")
        OUTPUT: error 非空, trace 有 status="error"
        """
        from app.subgraphs.option import extract_option

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM超时"))
        with patch("app.llm.clients.get_qwen_thinking") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await extract_option(_make_state("期权询价"))

        _show("extract_option LLM异常",
              {"error": "RuntimeError('LLM超时')"},
              {"error": result.get("error", ""),
               "trace_status": [t.get("status") for t in result.get("trace", [])]})
        assert result.get("error")
        assert any(t.get("status") == "error" for t in result.get("trace", []))


# ============================================================
# 五、check_param_limit（纯 Python，不 Mock）
# ============================================================
class TestCheckParamLimit:

    @pytest.mark.asyncio
    async def test_empty_order_list_skips(self):
        """空订单列表 → 跳过
        INPUT:  order_list = []
        OUTPUT: trace status="skip"
        """
        from app.subgraphs.option import check_param_limit
        result = await check_param_limit({"order_list": []})
        _show("check_param_limit 空列表",
              {"order_list": []},
              {"trace_status": result["trace"][0]["status"]})
        assert result["trace"][0]["status"] == "skip"

    @pytest.mark.asyncio
    async def test_not_exceeded_single(self):
        """单标的不超标
        INPUT:  order_list = [{"stock_code":"600519","strike_price":500,"tenor":"1M"}]
        OUTPUT: exceeded = False
        """
        from app.subgraphs.option import check_param_limit
        result = await check_param_limit({"order_list": [
            {"stock_code": "600519", "strike_price": 500, "tenor": "1M"},
        ]})
        _show("check_param_limit 不超标",
              {"order_count": 1},
              {"trace_status": result["trace"][0]["status"],
               "combo": result["trace"][0]["output_preview"]})
        assert result["trace"][0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_exceeded_stock_count(self):
        """标的数 > 5
        INPUT:  6 个不同 stock_code
        OUTPUT: error 包含 "标的数"
        """
        from app.subgraphs.option import check_param_limit
        order_list = [{"stock_code": f"00000{i}.SZ"} for i in range(6)]
        result = await check_param_limit({"order_list": order_list})
        _show("check_param_limit 标的超标",
              {"order_list": f"{len(order_list)}个不同标的"},
              {"error": result.get("error", "")})
        assert result.get("error")
        assert "标的数" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_exceeded_strike_count(self):
        """执行价数 > 5
        INPUT:  6 个不同 strike_price，同一 stock_code
        OUTPUT: error 包含 "执行价数"
        """
        from app.subgraphs.option import check_param_limit
        order_list = [
            {"stock_code": "600519.SH", "strike_price": (i + 1) * 100}
            for i in range(6)
        ]
        result = await check_param_limit({"order_list": order_list})
        _show("check_param_limit 执行价超标",
              {"order_list": f"6个不同strike"},
              {"error": result.get("error", "")})
        assert "执行价数" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_exceeded_tenor_count(self):
        """期限数 > 5
        INPUT:  6 个不同 tenor
        OUTPUT: error 包含 "期限数"
        """
        from app.subgraphs.option import check_param_limit
        order_list = [
            {"stock_code": "600519.SH", "tenor": f"{i}M"}
            for i in range(1, 7)
        ]
        result = await check_param_limit({"order_list": order_list})
        _show("check_param_limit 期限超标",
              {"order_list": "6个不同tenor"},
              {"error": result.get("error", "")})
        assert "期限数" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_exceeded_combo_count(self):
        """组合数 > 10
        INPUT:  3 stock_code × 2 strike_price × 2 tenor = 12 > 10
        OUTPUT: error 包含 "组合数"
        """
        from app.subgraphs.option import check_param_limit
        stocks = ["000001.SZ", "000002.SZ", "000003.SZ"]
        strikes = [100, 200]
        tenors = ["1M", "3M"]
        order_list = [
            {"stock_code": s, "strike_price": k, "tenor": t}
            for s in stocks for k in strikes for t in tenors
        ]
        result = await check_param_limit({"order_list": order_list})
        _show("check_param_limit 组合超标",
              {"order_list": f"3×2×2={len(order_list)}"},
              {"error": result.get("error", "")})
        assert "组合数" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_duplicate_dedup(self):
        """重复的 stock_code 只算一次
        INPUT:  7 个 order，但只有 3 个不同 stock_code
        OUTPUT: stock_count = 3, 不超标
        """
        from app.subgraphs.option import check_param_limit
        order_list = [
            {"stock_code": "000001.SZ"},
            {"stock_code": "000001.SZ"},
            {"stock_code": "000001.SZ"},
            {"stock_code": "000002.SZ"},
            {"stock_code": "000002.SZ"},
            {"stock_code": "000003.SZ"},
            {"stock_code": "000003.SZ"},
        ]
        result = await check_param_limit({"order_list": order_list})
        _show("check_param_limit 重复去重",
              {"order_list": "7条, 3个不同stock"},
              {"trace_status": result["trace"][0]["status"]})
        assert result["trace"][0]["status"] == "success"


# ============================================================
# 六、call_option_api（Mock OtcBackendClient）
# ============================================================
class TestCallOptionApi:

    @pytest.mark.asyncio
    async def test_normal_call(self):
        """正常调用后端
        INPUT:  intent="new_inquiry", operate="inquiry"
               backend 返回 code=0
        OUTPUT: api_code=0
        """
        from app.subgraphs.option import call_option_api

        mock_client = _mock_backend_client(code=0, result="询价已受理")
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            result = await call_option_api(_make_state(
                "期权询价", intent="new_inquiry", operate="inquiry", order_list=[],
            ))

        _show("call_option_api 正常",
              {"intent": "new_inquiry"},
              {"api_code": result["api_code"]})
        assert result["api_code"] == 0

    @pytest.mark.asyncio
    async def test_skip_when_has_error(self):
        """前面节点已有 error → 跳过 API 调用
        INPUT:  state.error = "参数超标"
        OUTPUT: api_code=400, trace status="skip"
        """
        from app.subgraphs.option import call_option_api

        result = await call_option_api(_make_state(
            "期权询价", error="参数超标", intent="new_inquiry",
        ))

        _show("call_option_api 有error跳过",
              {"error": "参数超标"},
              {"api_code": result["api_code"],
               "trace_status": result["trace"][0]["status"]})
        assert result["api_code"] == 400
        assert result["trace"][0]["status"] == "skip"

    @pytest.mark.asyncio
    async def test_backend_error(self):
        """后端返回业务错误
        INPUT:  backend 返回 code=500
        OUTPUT: api_code=500
        """
        from app.subgraphs.option import call_option_api

        mock_client = _mock_backend_client(code=500, result="服务不可用")
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            result = await call_option_api(_make_state(
                "期权询价", intent="new_inquiry", operate="",
            ))

        _show("call_option_api 后端500",
              {"intent": "new_inquiry"},
              {"api_code": result["api_code"]})
        assert result["api_code"] == 500

    @pytest.mark.asyncio
    async def test_network_error(self):
        """网络异常
        INPUT:  OtcBackendClient.__aenter__ 抛 TimeoutException
        OUTPUT: trace 有 status="error"
        """
        from app.subgraphs.option import call_option_api

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(side_effect=TimeoutError("超时"))
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            result = await call_option_api(
                _make_state("期权询价", intent="new_inquiry", operate=""))

        _show("call_option_api 网络异常",
              {"error": "TimeoutError"},
              {"trace_status": [t.get("status") for t in result.get("trace", [])]})
        assert any(t.get("status") == "error" for t in result.get("trace", []))


# ============================================================
# 七、子图整体（6 条拓扑路径）
# ============================================================
class TestOptionGraph:

    @pytest.mark.asyncio
    async def test_path1_quick_query(self):
        """路径1：快速询价（参与型看涨/雪球）→ 直连后端
        INPUT:  raw_content = "参与型看涨 腾讯控股 1个月"
               backend 返回 code=0
        OUTPUT: trace = [detect_quick_query, fast_query_api]
                trace 不含 extract_option / check_param_limit / call_option_api
                intent = "new_inquiry"
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.option import build_option_graph

        mock_client = _mock_backend_client(code=0, result="询价已受理")
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            g = build_option_graph().compile(checkpointer=InMemorySaver())
            result = await g.ainvoke(
                _make_state("参与型看涨 腾讯控股 1个月"),
                {"configurable": {"thread_id": "opt-q1"}},
            )

        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        _show("子图路径1: 快速询价",
              {"raw_content": "参与型看涨 腾讯控股 1个月"},
              {"intent": result.get("intent"), "api_code": result.get("api_code"),
               "trace_nodes": trace_nodes})
        assert "detect_quick_query" in trace_nodes
        assert "fast_query_api" in trace_nodes
        assert "extract_option" not in trace_nodes
        assert result.get("intent") == "new_inquiry"

    @pytest.mark.asyncio
    async def test_path2_standard_full_chain(self):
        """路径2：标准询价 → ticker → extract → check → call
        INPUT:  raw_content = "期权询价 腾讯控股 欧式看涨 行权价500 1M"
               ticker 已有缓存, LLM 返回 new_inquiry, check 不超标, backend code=0
        OUTPUT: trace 包含全部 5 个标准路径节点
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.option import build_option_graph

        mock_client = _mock_backend_client(code=0, result="询价已受理")
        mock_llm = _mock_llm_extract(type_="new_inquiry", operate="inquiry", order_list=[
            OptionOrderLeg(stock_code="600519.SH", option_type="欧式看涨",
                          strike_price=500.0, tenor="1M"),
        ])

        state = _make_state(
            "期权询价 腾讯控股 欧式看涨 行权价500 1M",
            resolved_tickers=[TickerCandidate(keyword="腾讯", wind_code="600519.SH")],
        )

        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client), \
             patch("app.llm.clients.get_qwen_thinking") as m_llm:
            m_llm.return_value.with_structured_output.return_value = mock_llm

            g = build_option_graph().compile(checkpointer=InMemorySaver())
            result = await g.ainvoke(state, {"configurable": {"thread_id": "opt-s1"}})

        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        _show("子图路径2: 标准全链路",
              {"raw_content": "期权询价 腾讯控股 欧式看涨 行权价500 1M"},
              {"intent": result.get("intent"), "api_code": result.get("api_code"),
               "trace_nodes": trace_nodes})
        assert "detect_quick_query" in trace_nodes
        assert "extract_option" in trace_nodes
        assert "check_param_limit" in trace_nodes
        assert "call_option_api" in trace_nodes
        assert result.get("api_code") == 0

    @pytest.mark.asyncio
    async def test_path3_param_limit_exceeded(self):
        """路径3：参数超标 → check_param_limit 检测超标，api_code=400
        INPUT:  6 个不同标的（不同 stock_code）
        OUTPUT: trace 包含 check_param_limit + call_option_api，api_code=400
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.option import build_option_graph

        mock_client = _mock_backend_client(code=0, result="询价已受理")
        # 6 个不同 stock_code — 标的数超标（>5）
        order_list = [
            OptionOrderLeg(stock_code=f"00000{i}.SZ", strike_price=500.0, tenor="1M")
            for i in range(6)
        ]
        mock_llm = _mock_llm_extract(type_="new_inquiry", operate="inquiry",
                                     order_list=order_list)

        state = _make_state(
            "期权询价 多个标的",
            resolved_tickers=[TickerCandidate(keyword=str(i), wind_code=f"00000{i}.SZ")
                            for i in range(6)],
        )

        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client), \
             patch("app.llm.clients.get_qwen_thinking") as m_llm:
            m_llm.return_value.with_structured_output.return_value = mock_llm

            g = build_option_graph().compile(checkpointer=InMemorySaver())
            result = await g.ainvoke(state, {"configurable": {"thread_id": "opt-p3"}})

        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        _show("子图路径3: 参数超标阻断",
              {"raw_content": "期权询价 多个标的", "order_count": 6},
              {"api_code": result.get("api_code"), "error": result.get("error", ""),
               "trace_nodes": trace_nodes})
        assert "check_param_limit" in trace_nodes
        assert "call_option_api" in trace_nodes
        assert result.get("api_code") == 400

    @pytest.mark.asyncio
    async def test_path4_empty_order_list(self):
        """路径4：LLM 返回空 order_list → 链路仍然走通
        INPUT:  LLM 返回 order_list=[]
        OUTPUT: trace 包含 check_param_limit + call_option_api，api_code=0
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.option import build_option_graph

        mock_client = _mock_backend_client(code=0, result="已受理（无明细）")
        mock_llm = _mock_llm_extract(type_="new_inquiry", operate="inquiry",
                                     order_list=[])

        state = _make_state(
            "期权询价",
            resolved_tickers=[TickerCandidate(keyword="腾讯", wind_code="600519.SH")],
        )

        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client), \
             patch("app.llm.clients.get_qwen_thinking") as m_llm:
            m_llm.return_value.with_structured_output.return_value = mock_llm

            g = build_option_graph().compile(checkpointer=InMemorySaver())
            result = await g.ainvoke(state, {"configurable": {"thread_id": "opt-p4"}})

        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        _show("子图路径4: 空order_list",
              {"raw_content": "期权询价", "order_list": []},
              {"api_code": result.get("api_code"),
               "trace_nodes": trace_nodes,
               "error": result.get("error"),
               "reply_text": (result.get("reply_text") or "")[:80]})
        # check_param_limit 遇空 order_list 跳过，call_option_api 正常调用得到 code=0
        # （check_param_completeness 在图中未挂载，空参数直接透传）
        assert "check_param_limit" in trace_nodes
        assert "call_option_api" in trace_nodes
        assert result.get("api_code") == 0

    @pytest.mark.asyncio
    async def test_path5_llm_error_degradation(self):
        """路径5：LLM 异常 → 链路降级，api_code=400
        INPUT:  LLM 抛 RuntimeError
        OUTPUT: extract_option 有 error 输出, call_option_api 跳过, api_code=400
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.option import build_option_graph

        mock_client = _mock_backend_client(code=0, result="不会调用到")
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM超时"))

        state = _make_state(
            "期权询价",
            resolved_tickers=[TickerCandidate(keyword="腾讯", wind_code="600519.SH")],
        )

        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client), \
             patch("app.llm.clients.get_qwen_thinking") as m_llm:
            m_llm.return_value.with_structured_output.return_value = mock_llm

            g = build_option_graph().compile(checkpointer=InMemorySaver())
            result = await g.ainvoke(state, {"configurable": {"thread_id": "opt-p5"}})

        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        _show("子图路径5: LLM异常降级",
              {"raw_content": "期权询价", "LLM": "RuntimeError"},
              {"api_code": result.get("api_code"), "error": result.get("error", ""),
               "trace_nodes": trace_nodes})
        assert "extract_option" in trace_nodes
        assert result.get("api_code") == 400

    @pytest.mark.asyncio
    async def test_path6_snowball_quick_query(self):
        """路径6：雪球快速询价
        INPUT:  raw_content = "雪球询价 腾讯控股"
        OUTPUT: fast_query_api 直连, intent="new_inquiry"
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.option import build_option_graph

        mock_client = _mock_backend_client(code=0, result="雪球询价已受理")
        with patch("app.subgraphs.option.OtcBackendClient", return_value=mock_client):
            g = build_option_graph().compile(checkpointer=InMemorySaver())
            result = await g.ainvoke(
                _make_state("雪球询价 腾讯控股"),
                {"configurable": {"thread_id": "opt-snow"}},
            )

        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        _show("子图路径6: 雪球快速询价",
              {"raw_content": "雪球询价 腾讯控股"},
              {"intent": result.get("intent"), "api_code": result.get("api_code"),
               "trace_nodes": trace_nodes})
        assert "fast_query_api" in trace_nodes
        assert result.get("intent") == "new_inquiry"

    def test_graph_has_6_nodes(self):
        """图结构完整性：6 个节点（含 ticker_identify 子图）
        OUTPUT: 6 个节点全部注册
        """
        from app.subgraphs.option import build_option_graph
        g = build_option_graph()
        expected = {"detect_quick_query", "fast_query_api", "ticker_identify",
                    "extract_option", "check_param_limit", "call_option_api"}
        _show("图结构: 6个节点",
              {"expected": sorted(expected)},
              {"actual": sorted(g.nodes)})
        assert expected.issubset(g.nodes)


# ============================================================
# 八、Pydantic 模型校验
# ============================================================
class TestOptionModels:

    def test_order_leg_defaults(self):
        """OptionOrderLeg 默认值
        INPUT:  stock_code="600519.SH"（仅必填）
        OUTPUT: option_type="欧式看涨", direction="buy", strike_price_type="absolute"
        """
        leg = OptionOrderLeg(stock_code="600519.SH")
        _show("OptionOrderLeg 默认值",
              {"stock_code": "600519.SH"},
              {"option_type": leg.option_type, "direction": leg.direction,
               "strike_price_type": leg.strike_price_type})
        assert leg.option_type == "欧式看涨"
        assert leg.direction == "buy"
        assert leg.strike_price_type == "absolute"

    def test_order_leg_full(self):
        """OptionOrderLeg 全字段
        INPUT:  全部字段显式赋值
        OUTPUT: 全部保留原值
        """
        leg = OptionOrderLeg(
            stock_code="0700.HK", stock_name="腾讯控股",
            option_type="欧式看跌", strike_price=450.0,
            strike_price_type="percent", tenor="3M",
            notional=1000000.0, quantity=1000, direction="sell",
            counterparty_id=10049, counterparty_name="临沂阿凡提",
        )
        _show("OptionOrderLeg 全字段",
              {"stock_code": "0700.HK"},
              {"fields": leg.model_dump()})
        assert leg.option_type == "欧式看跌"
        assert leg.direction == "sell"
        assert leg.strike_price == 450.0

    def test_extract_output_defaults(self):
        """OptionExtractOutput 默认值
        INPUT:  无参数构造
        OUTPUT: type="unknown", operate="", order_list=[]
        """
        out = OptionExtractOutput()
        _show("OptionExtractOutput 默认值",
              {"input": "{}"},
              {"type": out.type, "operate": out.operate,
               "order_list": out.order_list})
        assert out.type == "unknown"
        assert out.operate == ""
        assert out.order_list == []

    def test_extract_output_with_orders(self):
        """OptionExtractOutput 含订单列表
        INPUT:  type="new_inquiry", 含 2 条 order
        OUTPUT: order_list 长度 2
        """
        out = OptionExtractOutput(
            type="new_inquiry", operate="inquiry",
            order_list=[
                OptionOrderLeg(stock_code="600519.SH"),
                OptionOrderLeg(stock_code="000858.SZ"),
            ],
        )
        _show("OptionExtractOutput 含订单",
              {"type": "new_inquiry", "legs": 2},
              {"order_count": len(out.order_list)})
        assert len(out.order_list) == 2

    def test_param_limit_not_exceeded(self):
        """OptionParamLimit 不超标
        INPUT:  stock/strike/tenor 都 ≤ 5, combo ≤ 10
        OUTPUT: exceeded=False, reason=""
        """
        limit = OptionParamLimit(
            stock_count=3, strike_count=2, tenor_count=1,
            combo_count=6, exceeded=False,
        )
        _show("OptionParamLimit 不超标",
              {"stock": 3, "strike": 2, "tenor": 1, "combo": 6},
              {"exceeded": limit.exceeded, "reason": limit.reason})
        assert limit.exceeded is False
        assert limit.reason == ""

    def test_param_limit_exceeded_with_reason(self):
        """OptionParamLimit 超标
        INPUT:  stock_count=7, 手动设 exceeded=True
        OUTPUT: exceeded=True
        """
        limit = OptionParamLimit(
            stock_count=7, strike_count=1, tenor_count=1,
            combo_count=7, exceeded=True, reason="标的数 7 > 5",
        )
        _show("OptionParamLimit 超标",
              {"stock": 7, "reason": "标的数 7 > 5"},
              {"exceeded": limit.exceeded, "reason": limit.reason})
        assert limit.exceeded is True
        assert "7 > 5" in limit.reason
