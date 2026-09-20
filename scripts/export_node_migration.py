"""Export a source-checked Dify node mapping without importing the app or exporting DSL secrets."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mapping:
    title: str
    disposition: str
    targets: tuple[str, ...]
    prompts: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    product: str | None = None
    intent: str | None = None
    note: str = "静态实现对应；业务等价及现场验收未由本清单证明。"


def mapping(title: str, mode: str, targets: str, *, prompts: str = "", tests: str = "",
            product: str | None = None, intent: str | None = None,
            note: str = "静态实现对应；业务等价及现场验收未由本清单证明。") -> Mapping:
    return Mapping(title, mode, tuple(targets.split()), tuple(prompts.split()), tuple(tests.split()), product, intent, note)


# This is migration metadata, not business-name/security dictionaries. IDs and titles are
# checked against the supplied snapshot; missing or renamed targets become pending.
MAPPINGS = {
    "1755072621769": mapping("开始", "合并(Code)", "app/api/turn_state.py:inputs_to_state app/nodes/ingest.py:ingest", tests="tests/test_api_turn_inputs.py"),
    "1755072896717": mapping("脚本判断期权、互换、其他查询指令", "Code", "app/nodes/route_rules.py:classify_trade_type", tests="tests/test_intent_route.py"),
    "1755072935885": mapping("条件分支", "合并(Code)", "app/graph/main.py:_route_after_intent app/subgraphs/swap/graph.py:_route_swap_entry", tests="tests/subgraphs/swap/test_graph_routing.py"),
    "1786439000001": mapping("互换-全新下单交易对手识别", "LLM+Code", "app/subgraphs/swap/fresh_counterparty.py:swap_recognize_fresh_counterparty app/subgraphs/swap/aggregate.py:unique_fresh_counterparty", prompts="swap/fresh_counterparty", tests="tests/subgraphs/swap/test_fresh_counterparty_graph.py", product="swap", note="完整授权名称走 Code；复杂召回仍用 LLM，随后唯一授权匹配。"),
    "1755073106378": mapping("期权-意图识别", "LLM+Code", "app/subgraphs/option/intent.py:option_intent", prompts="option/intent", tests="tests/subgraphs/option/test_intent.py", product="option"),
    "1755074179773": mapping("变量聚合器", "合并(Code)", "app/graph/main.py:build_main_graph app/nodes/render.py:render", tests="tests/test_smoke.py", note="独立变量聚合节点由 State 写回面和统一 render 取代；非逐节点同构。"),
    "1755075270023": mapping("存储消息意图-最终回复", "合并(Code)", "app/nodes/persist_intent.py:make_persist_intent app/tools/message_client.py:MessageClientHttpx.set_intent", tests="tests/test_smoke.py", note="各出口统一到 persist_intent；调用是否开启由应用环境决定，回复时序需接口验收。"),
    "1755075440773": mapping("直接回复", "合并(Code)", "app/nodes/render.py:render app/api/routes.py:_state_to_outputs", tests="tests/test_api_turn_inputs.py"),
    "1755075477466": mapping("输入参数收集至AIGC", "删除 / 原生审计替代", "app/checkpointer/factory.py:init_checkpointer app/api/routes.py:_execute_workflow app/api/idempotency.py:MySQLIdempotencyStore.begin app/api/idempotency.py:MySQLIdempotencyStore.complete app/nodes/persist.py:_write_to_mysql app/observability/tracing.py:attach_request_trace", tests="tests/test_api_turn_inputs.py tests/test_shared_database.py", note="确认退役 Dify 专属输入监控 HTTP 调用；Java 消费者依赖 Dify app/run ID 拉取详情，不适用于真实 LangGraph ID。由 checkpoint、message_log、node_trace 和 Langfuse 分担审计；不伪造 Dify 标识，不承诺 Java 旧 Dify 监控 UI 等价。权威 Java 引用见退役依据节。"),
    "1755500828121": mapping("直接回复 2", "合并(Code)", "app/nodes/fallback.py:fallback app/nodes/render.py:render", tests="tests/test_smoke.py"),
    "1756519920880": mapping("判断快速询价", "Code", "app/graph/main.py:_route_entry app/nodes/fast_query.py:is_fast_query app/nodes/fast_query.py:is_existing_command", tests="tests/nodes/test_fast_query.py"),
    "1756520149629": mapping("参与型看涨、雪球调询价参数解析", "合并(Code)", "app/nodes/fast_query.py:quick_inquiry app/tools/goats_agent_client.py:GoatsAgentClientHttpx.parse_rfq_instrument", tests="tests/nodes/test_fast_query.py", note="Code 调用 GOATS parser；外部 parser 是否使用模型不在本仓静态计数范围。"),
    "17580727448860": mapping("存量兼容-交易查询指令", "Code", "app/nodes/fast_query.py:existing_command_query app/tools/goats_agent_client.py:GoatsAgentClientHttpx.query_instruction", tests="tests/nodes/test_fast_query.py"),
    "1761213989319": mapping("互换-图片识别", "LLM+Code", "app/subgraphs/swap/multimodal.py:swap_image_order app/subgraphs/swap/multimodal_evidence.py:ImageTranscription", prompts="swap/image_ocr", tests="tests/subgraphs/swap/test_multimodal_evidence.py", note="视觉模型只逐字转写；附件证据是转写，不是像素正确性的保证。"),
    "17615583158280": mapping("存储消息意图", "合并(Code)", "app/nodes/persist_intent.py:make_persist_intent app/tools/message_client.py:MessageClientHttpx.set_intent", tests="tests/test_smoke.py"),
    "1764752494705": mapping("解析Excel", "Code", "app/subgraphs/swap/multimodal.py:swap_excel_order app/subgraphs/swap/multimodal_evidence.py:excel_evidence_rows", tests="tests/subgraphs/swap/test_multimodal_evidence.py"),
    "1764752539169": mapping("Excel-互换-请求下单参数解析", "LLM+Code", "app/subgraphs/swap/multimodal.py:swap_excel_order app/subgraphs/swap/multimodal.py:_extract_candidates app/subgraphs/swap/multimodal_evidence.py:normalize_attachment_candidates app/subgraphs/swap/multimodal_evidence.py:lock_attachment_bindings", prompts="swap/excel_extract", tests="tests/subgraphs/swap/test_multimodal_evidence.py", note="按附件行抽候选；Code 归一化和单位换算，GOATS/授权账户绑定后锁定。"),
    "1764752644850": mapping("模型数据聚合", "合并(Code)", "app/subgraphs/swap/graph.py:build_swap_graph app/subgraphs/swap/place_order.py:swap_place_order_submit", tests="tests/subgraphs/swap/test_graph_routing.py", note="文本/图片/Excel 通过统一 place_params 汇入 submit；旧聚合节点无独立同名节点。"),
    "1764841677781": mapping("图片-互换-请求下单参数解析", "LLM+Code", "app/subgraphs/swap/multimodal.py:swap_image_order app/subgraphs/swap/multimodal.py:_extract_candidates app/subgraphs/swap/multimodal_evidence.py:normalize_attachment_candidates app/subgraphs/swap/multimodal_evidence.py:lock_attachment_bindings", prompts="swap/image_extract", tests="tests/subgraphs/swap/test_multimodal_evidence.py", note="只抽原文候选；归一化、证券校验、授权账户及最终锁定由 Code 执行。"),
    "1772589205439": mapping("期权平仓-意图识别", "LLM+Code", "app/subgraphs/close/intent.py:close_intent", prompts="option_close/intent", tests="tests/subgraphs/close/test_intent.py", product="option_close"),
    "1772594713580": mapping("条件分支 6", "Code", "app/subgraphs/close/graph.py:_route_after_close_intent", tests="tests/subgraphs/close/test_graph_routing.py"),
    "1772602519902": mapping("请求下单和确认全部平仓参数提取", "LLM+Code", "app/subgraphs/close/place_close.py:place_close_extract app/subgraphs/close/normalization.py:normalize_place_candidates app/subgraphs/close/place_close.py:place_close_validate", prompts="option_close/place_close", tests="tests/subgraphs/close/test_candidate_migration.py", product="option_close", intent="close_order_request"),
    "1772606114116": mapping("期权平仓-参数聚合", "合并(Code)", "app/subgraphs/close/aggregate.py:build_close_order_req_vo app/subgraphs/close/backend.py:call_close_backend", tests="tests/subgraphs/close/test_aggregate.py"),
    "1772614623517": mapping("期权平仓-持仓查询参数提取", "LLM+Code", "app/subgraphs/close/holding_query.py:close_holding_query app/subgraphs/close/normalization.py:normalize_holding_candidates", prompts="option_close/holding_query", tests="tests/subgraphs/close/test_candidate_migration.py", product="option_close", intent="close_order_query"),
    "1772615066119": mapping("确认平仓", "Code", "app/subgraphs/close/confirm_close.py:close_confirm_close app/subgraphs/close/order_id.py:extract_for_close_orders", tests="tests/subgraphs/close/test_confirm_cancel_close.py", product="option_close", intent="close_order_confirm", note="旧 LLM 参数提取已删除；Code 确定目标，意图层仍可能使用模型。"),
    "1772616579608": mapping("撤单参数提取", "Code", "app/subgraphs/close/cancel_close.py:close_cancel_close app/subgraphs/close/order_id.py:extract_for_close_orders", tests="tests/subgraphs/close/test_confirm_cancel_close.py", product="option_close", intent="close_order_cancel_request"),
    "1772617956918": mapping("确认撤单参数提取", "Code", "app/subgraphs/close/confirm_cancel.py:close_confirm_cancel app/subgraphs/close/order_id.py:extract_for_close_orders", tests="tests/subgraphs/close/test_confirm_cancel_query_status.py", product="option_close", intent="close_order_cancel_confirm"),
    "1772677545585": mapping("平仓参数提取-引用消息解析", "Code", "app/subgraphs/close/place_close.py:place_close_parse app/subgraphs/close/reference_parser.py:parse_reference_message", tests="tests/subgraphs/close/test_reference_parser.py", product="option_close", intent="close_order_request"),
    "1772678099736": mapping("平仓参数提取-合并输出", "合并(Code)", "app/subgraphs/close/place_close.py:place_close_normalize app/subgraphs/close/normalization.py:normalize_place_candidates", tests="tests/subgraphs/close/test_candidate_migration.py", product="option_close", intent="close_order_request", note="活跃路径使用候选归一化；不能把仍保留的旧 merge.py 当成当前调用证明。"),
    "1772707335701": mapping("平仓订单查询", "Code", "app/subgraphs/close/query_status.py:close_query_status app/subgraphs/close/order_id.py:extract_for_query", tests="tests/subgraphs/close/test_confirm_cancel_query_status.py", product="option_close", intent="close_order_order_query"),
    "1772773805306": mapping("交易对手、候选标的提取", "Code", "app/nodes/pre_route.py:pre_route app/nodes/pre_route.py:parse_counterparties app/nodes/pre_route.py:parse_candidates", tests="tests/nodes/test_pre_route.py"),
    "1776159951508": mapping("互换-节点-意图识别", "LLM+Code", "app/subgraphs/swap/intent.py:swap_intent", prompts="swap/intent", tests="tests/subgraphs/swap/test_intent.py", product="swap"),
    "1776160524740": mapping("互换-意图路由", "Code", "app/subgraphs/swap/graph.py:_route_after_swap_intent", tests="tests/subgraphs/swap/test_graph_routing.py"),
    "1776160580437": mapping("互换-节点-下单", "LLM+Code", "app/subgraphs/swap/place_order.py:swap_extract_candidates app/subgraphs/swap/place_order.py:swap_normalize app/subgraphs/swap/place_order.py:swap_resolve app/subgraphs/swap/place_order.py:swap_place_result", prompts="swap/place_order", tests="tests/subgraphs/swap/test_place_evidence.py tests/subgraphs/swap/test_fresh_counterparty_graph.py", product="swap", intent="place_order_request"),
    "1776160728475": mapping("互换-确认下单协议解析", "Code", "app/subgraphs/swap/confirmation.py:parse_confirmation app/subgraphs/swap/confirm.py:swap_confirm", tests="tests/subgraphs/swap/test_confirmation_protocol.py", product="swap", intent="confirm_order", note="严格确认、引用范围及非法输入零写请求；50 条协议专项独立于 388 黄金集。"),
    "1781200000774": mapping("互换-确认指令分流", "Code", "app/subgraphs/swap/confirmation.py:is_confirmation app/subgraphs/swap/intent.py:swap_intent", tests="tests/subgraphs/swap/test_confirmation_protocol.py"),
    "1776161179315": mapping("互换-节点-撤单", "Code", "app/subgraphs/swap/cancel.py:swap_cancel app/subgraphs/swap/order_id.py:extract_for_cancel", tests="tests/subgraphs/swap/test_cancel_scope.py", product="swap", intent="cancel_order_request"),
    "1776161199939": mapping("互换-节点-确认撤单", "Code", "app/subgraphs/swap/confirm.py:swap_confirm app/subgraphs/swap/order_id.py:extract_for_confirm_single", tests="tests/subgraphs/swap/test_confirm_cancel_query.py", product="swap", intent="confirm_cancel_order"),
    "1776161205019": mapping("互换-节点-确认改单", "Code", "app/subgraphs/swap/confirm.py:swap_confirm app/subgraphs/swap/order_id.py:extract_for_confirm_single", tests="tests/subgraphs/swap/test_confirm_cancel_query.py", product="swap", intent="confirm_modify_order"),
    "1776161209987": mapping("互换-节点-查询订单", "Code", "app/subgraphs/swap/query_order.py:swap_query_order app/subgraphs/swap/order_id.py:extract_for_query", tests="tests/subgraphs/swap/test_confirm_cancel_query.py", product="swap", intent="query_order_status"),
    "1776161938187": mapping("互换参数统一聚合", "合并(Code)", "app/subgraphs/swap/apply_picks.py:swap_apply_picks app/subgraphs/swap/backend.py:call_swap_backend", tests="tests/subgraphs/swap/test_select_chain.py", note="按各意图 DTO 在调用边界组装；不再依赖一个通用参数聚合节点。"),
    "1776165163547": mapping("成功判断到意图", "合并(Code)", "app/nodes/intent_route.py:intent_route", tests="tests/test_intent_route.py"),
    "1776755680654": mapping("获取订单信息", "Code", "app/subgraphs/close/place_close.py:place_close_fetch_orders app/subgraphs/close/place_close.py:_fetch_order_data app/tools/option_client.py:OptionClientHttpx.query_close_orders", tests="tests/subgraphs/close/test_candidate_migration.py"),
    "1776755964286": mapping("格式化订单数据", "合并(Code)", "app/subgraphs/close/place_close.py:place_close_fetch_orders app/subgraphs/close/place_close.py:_build_user_message", tests="tests/subgraphs/close/test_candidate_migration.py", note="后端结构验证和候选上下文格式化合并进获取/提取阶段。"),
    "1779329617925": mapping("条件分支 8", "Code", "app/subgraphs/option/graph.py:_route_after_option_intent", tests="tests/subgraphs/option/test_graph_routing.py"),
    "1779330004958": mapping("期权-节点-询价", "LLM+Code", "app/subgraphs/option/extract_inquiry.py:inquiry_extract app/subgraphs/option/extract_inquiry.py:inquiry_normalize app/subgraphs/option/extract_inquiry.py:inquiry_resolve", prompts="option/extract_inquiry", tests="tests/subgraphs/option/test_inquiry_evidence.py", product="option", intent="new_inquiry"),
    "17793301761160": mapping("期权-节点-确认下单", "Code", "app/subgraphs/option/extract_confirm_place.py:option_extract_confirm_place app/subgraphs/option/place_params.py:parse_confirm_place_params", tests="tests/subgraphs/option/test_extract_confirm_place.py", product="option", intent="confirm_order"),
    "17793301774310": mapping("期权-节点-查询订单状态", "Code", "app/subgraphs/option/extract_query.py:option_extract_query app/subgraphs/option/order_id.py:extract_for_query", tests="tests/subgraphs/option/test_extract_query.py", product="option", intent="query_order_status"),
    "17793301778710": mapping("期权-节点-撤单请求", "Code", "app/subgraphs/option/extract_cancel.py:option_extract_cancel app/subgraphs/option/order_id.py:extract_for_request_cancel", tests="tests/subgraphs/option/test_extract_cancel.py", product="option", intent="request_cancel_order"),
    "17793301782150": mapping("期权-节点-确认撤单", "Code", "app/subgraphs/option/extract_confirm_cancel.py:option_extract_confirm_cancel app/subgraphs/option/order_id.py:extract_for_confirm_cancel", tests="tests/subgraphs/option/test_extract_confirm_cancel.py", product="option", intent="confirm_cancel_order"),
    "17793301871440": mapping("期权-节点-下单", "Code", "app/subgraphs/option/extract_place.py:option_extract_place app/subgraphs/option/place_params.py:parse_place_params", tests="tests/subgraphs/option/test_extract_place.py", product="option", intent="place_order_from_quote"),
    "17793301887260": mapping("期权-节点-取消下单", "Code", "app/subgraphs/option/extract_cancel_place.py:option_extract_cancel_place app/subgraphs/option/order_id.py:extract_for_cancel_place", tests="tests/subgraphs/option/test_extract_cancel_place.py", product="option", intent="cancel_order_request"),
    "1779330741414": mapping("期权参数统一聚合", "合并(Code)", "app/subgraphs/option/backend.py:call_option_backend app/graph/business_params.py:validated_place_params", tests="tests/subgraphs/option/test_backend.py"),
    "1779435568671": mapping("unknown意图兜底识别", "LLM+Code", "app/nodes/intent_route.py:_classify_with_llm app/nodes/intent_route.py:intent_route", prompts="router/unknown_intent", tests="tests/test_intent_evidence.py"),
    "1779435765800": mapping("兜底意图识别到意图", "合并(Code)", "app/graph/main.py:_route_after_intent", tests="tests/test_intent_route.py"),
    "1779437119716": mapping("意图聚合", "合并(Code)", "app/nodes/intent_route.py:intent_route app/graph/state.py:AgentState", tests="tests/test_intent_evidence.py"),
    "17797951842080": mapping("最大跟量公共prompt", "合并(Code)", "app/subgraphs/option/place_params.py:_extract_fast_execution app/subgraphs/swap/normalize.py:normalize_field app/subgraphs/close/normalization.py:normalize_place_candidates", tests="tests/subgraphs/swap/test_normalize_fields.py", note="当前无公共 prompt 生成节点；语义分配到各业务 Code。旧 Code 中动态生成提示内容不纳入本表字符统计，跨产品规则一致性待业务验收。"),
    "17801169478740": mapping("存储消息意图-期权开仓", "合并(Code)", "app/nodes/persist_intent.py:make_persist_intent app/tools/message_client.py:MessageClientHttpx.set_intent", tests="tests/test_smoke.py"),
    "17801169587010": mapping("直接回复-期权开仓", "合并(Code)", "app/nodes/render.py:render", tests="tests/test_smoke.py"),
    "17801170559040": mapping("存储消息意图-期权平仓", "合并(Code)", "app/nodes/persist_intent.py:make_persist_intent app/tools/message_client.py:MessageClientHttpx.set_intent", tests="tests/test_smoke.py"),
    "17801170632810": mapping("直接回复-期权平仓", "合并(Code)", "app/nodes/render.py:render", tests="tests/test_smoke.py"),
    "1780144732150": mapping("期权快速询价", "合并(Code)", "app/nodes/fast_query.py:quick_inquiry app/tools/option_client.py:OptionClientHttpx.operate", tests="tests/nodes/test_fast_query.py"),
    "1780144986217": mapping("期权平仓", "Code", "app/subgraphs/close/backend.py:call_close_backend app/tools/option_client.py:OptionClientHttpx.operate", tests="tests/subgraphs/close/test_backend.py", product="option_close"),
    "1780145251793": mapping("期权开仓", "Code", "app/subgraphs/option/backend.py:call_option_backend app/tools/option_client.py:OptionClientHttpx.operate", tests="tests/subgraphs/option/test_backend.py", product="option"),
    "1780145473883": mapping("互换开仓", "Code", "app/subgraphs/swap/backend.py:call_swap_backend app/tools/swap_client.py:SwapClientHttpx.operate", tests="tests/subgraphs/swap/test_backend.py", product="swap", note="同一个 Java operate 承担互换开仓/平仓/确认/查询；不是另有一个互换平仓子图。"),
    "1780652808839": mapping("互换-选择交易对手", "LLM+Code", "app/subgraphs/swap/select_counterparty.py:swap_select_counterparty app/subgraphs/swap/selection_rules.py:counterparty_choice app/subgraphs/swap/selection_rules.py:validate_picks", prompts="swap/select_counterparty", tests="tests/subgraphs/swap/test_selection_evidence.py", note="明确多订单范围优先 Code；模型只定位连续证据，授权身份由代码取值。"),
    "1780652892832": mapping("互换-选择标的", "LLM+Code", "app/subgraphs/swap/select_ticker.py:swap_select_ticker app/subgraphs/swap/select_ticker.py:_verify_selected_codes app/subgraphs/swap/selection_rules.py:ticker_choice", prompts="swap/select_ticker", tests="tests/subgraphs/swap/test_selection_evidence.py", note="明确范围优先 Code；引用候选须经当前 GOATS 校验，不允许未知 directRef 原样下发。"),
    "1780652971845": mapping("互换-标的对手覆盖聚合", "Code", "app/subgraphs/swap/apply_picks.py:swap_apply_picks app/subgraphs/swap/aggregate.py:match_order_index", tests="tests/subgraphs/swap/test_selection_evidence.py"),
    "1781075165428": mapping("互换-规整引用补参摘要", "Code", "app/subgraphs/swap/quote_hints.py:refine_quote_hints", tests="tests/subgraphs/swap/test_quote_hints.py"),
    "1781099900001": mapping("互换-引用消息判空", "Code", "app/subgraphs/swap/graph.py:_has_usable_quote app/subgraphs/swap/graph.py:_route_after_place_order", tests="tests/subgraphs/swap/test_graph_routing.py"),
    "1781120000001": mapping("期权开仓-前置清洗", "Code", "app/subgraphs/option/sanitize.py:sanitize_order_list app/subgraphs/option/backend.py:call_option_backend", tests="tests/subgraphs/option/test_sanitize.py"),
    "1781120000002": mapping("期权平仓-前置清洗", "Code", "app/subgraphs/close/aggregate.py:sanitize_close_order_req_vo app/subgraphs/close/backend.py:call_close_backend", tests="tests/subgraphs/close/test_aggregate.py"),
    "1781120000003": mapping("互换开仓-前置清洗", "Code", "app/subgraphs/swap/prewash.py:sanitize_order_list app/subgraphs/swap/backend.py:call_swap_backend", tests="tests/subgraphs/swap/test_prewash.py"),
}


# External effects / models used by the mapped stage, verified by current source symbols.
TOOLS = {
    "1786439000001": "app/llm/clients.py:get_qwen_complex",
    "1755073106378": "app/llm/clients.py:get_qwen_structured",
    "1755075270023": "app/tools/message_client.py:MessageClientHttpx.set_intent",
    "1756520149629": "app/tools/goats_agent_client.py:GoatsAgentClientHttpx.parse_rfq_instrument",
    "17580727448860": "app/tools/goats_agent_client.py:GoatsAgentClientHttpx.query_instruction",
    "1761213989319": "app/llm/clients.py:get_qwen_vl",
    "17615583158280": "app/tools/message_client.py:MessageClientHttpx.set_intent",
    "1764752494705": "app/subgraphs/swap/multimodal.py:_fetch_bytes app/subgraphs/swap/multimodal_evidence.py:excel_evidence_rows",
    "1764752539169": "app/llm/clients.py:get_qwen_structured app/tools/ticker_client.py:TickerClientHttpx.search_securities_instrument",
    "1764841677781": "app/llm/clients.py:get_qwen_structured app/tools/ticker_client.py:TickerClientHttpx.search_securities_instrument",
    "1772589205439": "app/llm/clients.py:get_qwen_thinking",
    "1772602519902": "app/llm/clients.py:get_qwen_thinking",
    "1772614623517": "app/llm/clients.py:get_qwen_thinking app/tools/option_client.py:OptionClientHttpx.operate",
    "1776159951508": "app/llm/clients.py:get_qwen_thinking",
    "1776160580437": "app/llm/clients.py:get_qwen_complex app/tools/ticker_client.py:TickerClientHttpx.search_securities_instrument",
    "1776755680654": "app/tools/option_client.py:OptionClientHttpx.query_close_orders",
    "1779330004958": "app/llm/clients.py:get_qwen_thinking app/tools/ticker_client.py:TickerClientHttpx.search_securities_instrument",
    "1779435568671": "app/llm/clients.py:get_qwen_thinking",
    "17801169478740": "app/tools/message_client.py:MessageClientHttpx.set_intent",
    "17801170559040": "app/tools/message_client.py:MessageClientHttpx.set_intent",
    "1780144732150": "app/tools/option_client.py:OptionClientHttpx.operate",
    "1780144986217": "app/tools/option_client.py:OptionClientHttpx.operate",
    "1780145251793": "app/tools/option_client.py:OptionClientHttpx.operate",
    "1780145473883": "app/tools/swap_client.py:SwapClientHttpx.operate",
    "1780652808839": "app/llm/clients.py:get_qwen_complex",
    "1780652892832": "app/llm/clients.py:get_qwen_complex app/tools/ticker_client.py:TickerClientHttpx.search_securities_instrument",
}


# Audited Java contract: the old collector dispatches Dify-specific asynchronous reads.
# Anchors are source-code identifiers, never configuration values or credentials.
_JAVA_MONITOR = "yudao-module-monitor/yudao-module-monitor-biz/src/main/java/cn/iocoder/yudao/module/monitor/"
AUDIT_RETIREMENT_REFERENCES = (
    ("controller/admin/chatflow/DifyChatFlowLogController.java", "return CommonResult.success(true);", "Controller 调 sendChatFlowInput 后固定 ACK；不证明异步日志成功。"),
    ("controller/admin/chatflow/vo/DifyChatFlowInputVO.java", "private String sysAppId", "DTO 使用 Dify sysAppId / sysWorkflowId / sysWorkflowRunId 身份。"),
    ("service/chatflow/DifyChatFlowServiceImpl.java", "difyWorkflowInputParameterService.createDifyWorkflowInputParameter(reqVO);", "先写 Dify 输入表，再发送 RabbitMQ；外围 catch 吞掉处理失败。"),
    ("service/chatflow/DifyChatFlowServiceImpl.java", "getEnableIntegrationSystem(IntegrationEnum.integrationSystemType.DIFY.getCode())", "消费逻辑固定选择 DIFY 集成类型。"),
    ("service/chatflow/DifyChatFlowServiceImpl.java", "getWorkflowRunDetail(enableIntegrationSystem, difyChatFlowInput.getSysAppId(), difyChatFlowInput.getSysWorkflowRunId())", "真实 Dify app/run ID 用于拉取运行详情。"),
    ("service/chatflow/DifyChatFlowServiceImpl.java", "getWorkflowRunNodeExecutionList(enableIntegrationSystem, difyChatFlowInput.getSysAppId(), difyChatFlowInput.getSysWorkflowRunId())", "继续按 Dify app/run ID 拉节点详情。"),
    ("service/chatflow/DifyChatFlowServiceImpl.java", ".setSavedLog(1)", "Dify 详情处理成功后才设置 Java 消息 savedLog。"),
    ("mq/consumer/dify/DifyChatFlowInputRabbitConsumer.java", "difyChatFlowService.doSendChatFlowInputRabbit(message)", "RabbitMQ 消费者进入 Dify 拉取逻辑，后续有延迟重试。"),
)


def audit_retirement_evidence(java_root: Path | None) -> list[dict[str, Any]]:
    evidence = []
    for relative, anchor, meaning in AUDIT_RETIREMENT_REFERENCES:
        source = _JAVA_MONITOR + relative
        item: dict[str, Any] = {"java_relative_path": source, "meaning": meaning, "verified": False}
        if java_root is not None:
            path = java_root / source
            item["path"] = str(path)
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                matches = [line for line, value in enumerate(text.splitlines(), 1) if anchor in value]
                item.update(verified=len(matches) == 1, lines=matches,
                            sha256=hashlib.sha256(text.encode()).hexdigest())
        evidence.append(item)
    return evidence


class SourceIndex:
    def __init__(self, root: Path):
        self.root = root
        self.sources: dict[str, str] = {}
        self.trees: dict[str, ast.Module] = {}
        self.symbols: dict[str, dict[str, ast.AST]] = {}

    def read(self, relative: str) -> str:
        if relative not in self.sources:
            self.sources[relative] = (self.root / relative).read_text(encoding="utf-8")
        return self.sources[relative]

    def tree(self, relative: str) -> ast.Module:
        if relative not in self.trees:
            self.trees[relative] = ast.parse(self.read(relative))
        return self.trees[relative]

    def reference(self, reference: str) -> dict[str, Any]:
        relative, _, symbol = reference.partition(":")
        if not (self.root / relative).is_file():
            return {"reference": reference, "verified": False, "reason": "文件不存在"}
        if relative not in self.symbols:
            found: dict[str, ast.AST] = {}
            def visit(node: ast.AST, prefix: str = "") -> None:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        qualified = prefix + child.name
                        found[qualified] = child
                        visit(child, qualified + ".")
            visit(self.tree(relative))
            self.symbols[relative] = found
        node = self.symbols[relative].get(symbol)
        if node is None:
            return {"reference": reference, "verified": False, "reason": "符号不存在"}
        return {"reference": reference, "verified": True, "path": relative,
                "symbol": symbol, "line": node.lineno, "kind": type(node).__name__,
                "sha256": hashlib.sha256(self.read(relative).encode()).hexdigest()}


def dsl_metadata(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Allowlist fields only. Code bodies, prompts, variables, URLs and secrets never leave here."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    graph = document["workflow"]["graph"]
    nodes = []
    for node in graph["nodes"]:
        data = node.get("data") or {}
        prompts = data.get("prompt_template") or []
        nodes.append({"id": str(node["id"]), "title": str(data.get("title") or ""),
                      "original_type": str(data.get("type") or "unknown"),
                      "before_system_chars": sum(len(part.get("text", "").strip()) for part in prompts
                                                 if isinstance(part, dict) and part.get("role") == "system"),
                      "before_all_template_chars": sum(len(part.get("text", "").strip()) for part in prompts
                                                       if isinstance(part, dict))})
    edges = [{"source": str(edge["source"]), "target": str(edge["target"]),
              "source_handle": str(edge.get("sourceHandle") or "")}
             for edge in graph["edges"]]
    ids = [node["id"] for node in nodes]
    if len(set(ids)) != len(ids) or any(edge[key] not in ids for edge in edges for key in ("source", "target")):
        raise ValueError("DSL graph IDs must be unique and edge endpoints must exist")
    return nodes, edges


def prompt_index(index: SourceIndex) -> dict[str, dict[str, Any]]:
    result = {}
    expression = re.compile(r"##\s*\[system\]\s*\n+```[a-zA-Z]*\n(.*?)\n```(?=\s*(?:##\s*\[|\Z))", re.DOTALL)
    for path in sorted((index.root / "app").rglob("*.py")):
        relative = str(path.relative_to(index.root))
        for node in ast.walk(index.tree(relative)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "PromptSpec":
                continue
            fields = {item.arg: item.value for item in node.keywords}
            category, name = fields.get("category"), fields.get("name")
            if not isinstance(category, ast.Constant) or not isinstance(name, ast.Constant):
                continue
            key = f"{category.value}/{name.value}"
            prompt_path = f"app/prompts/{key}.md"
            exists = (index.root / prompt_path).is_file()
            text = index.read(prompt_path) if exists else ""
            match = expression.search(text)
            result[key] = {"path": prompt_path, "registration": f"{relative}:{node.lineno}",
                           "system_chars": len(match[1].strip()) if match else None,
                           "output_model_expression": ast.unparse(fields["output_model"]) if "output_model" in fields else None,
                           "sha256": hashlib.sha256(text.encode()).hexdigest() if exists else None}
    return result


def fixture_index(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted((root / "tests/fixtures/categories").glob("*.jsonl")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            case = json.loads(line)
            identity = case.get("id") or case.get("caseNo") or case.get("case_id")
            for turn, item in enumerate([case, *(case.get("sub_scenes") or [])], 1):
                expected = item.get("expected") or {}
                result.append({"case_id": identity, "turn": turn, "path": str(path.relative_to(root)),
                               "line": line_number, "product": expected.get("product_type"),
                               "intent": expected.get("intent")})
    return result


def test_evidence(plan: Mapping, index: SourceIndex, fixtures: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tests, literals = [], set()
    for relative in plan.tests:
        path = index.root / relative
        if not path.is_file():
            tests.append({"path": relative, "verified": False})
            continue
        tree = index.tree(relative)
        names = [{"name": node.name, "line": node.lineno} for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
        tests.append({"path": relative, "verified": True, "test_functions": names})
        literals.update(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str))
    cases = []
    for item in fixtures:
        if item["case_id"] in literals:
            cases.append({**item, "basis": "关联测试文件中出现完整 case_id 字面量（静态关联，非执行结果）"})
        elif plan.product and plan.intent and item["product"] == plan.product and item["intent"] == plan.intent:
            cases.append({**item, "basis": "该轮 expected.product_type / intent 明确匹配（非执行证明）"})
    return tests, cases


def schema_sources(index: SourceIndex, java_root: Path | None) -> dict[str, Any]:
    references = ["app/subgraphs/swap/models.py:SwapOrderItem", "app/subgraphs/option/models.py:OptionInquiryRawItem",
                  "app/subgraphs/close/models.py:CloseOrderItem", "app/subgraphs/close/models.py:HoldingQueryParams",
                  "app/tools/swap_client.py:SwapOrderOpenApiBaseSaveReqVO", "app/tools/option_client.py:FinancialOrderOpenApiBaseSaveReqVO"]
    java = []
    if java_root:
        for name in ("SwapOrderOpenApiBaseSaveReqVO", "FinancialOrderOpenApiBaseSaveReqVO"):
            matches = sorted(java_root.rglob(name + ".java"))
            java.append({"class": name, "paths": [str(path) for path in matches], "unique": len(matches) == 1,
                         "sha256": hashlib.sha256(matches[0].read_bytes()).hexdigest() if len(matches) == 1 else None})
    slots = [str(path.relative_to(index.root)) for path in index.root.glob("**/slot_schema.json")
             if not any(part in {".venv", ".git", "node_modules"} for part in path.parts)]
    return {"slot_schema_files": slots, "note": "规范引用的 slot_schema.json / 50 字段未提供；不虚构补齐。实际 Java DTO、Pydantic 输出及候选模型是本轮可核对来源。",
            "python": [index.reference(reference) for reference in references], "java": java}


def generate(project_root: Path, dsl: Path, output_prefix: Path, java_root: Path | None = None) -> dict[str, Any]:
    index = SourceIndex(project_root)
    nodes, edges = dsl_metadata(dsl)
    prompts, fixtures = prompt_index(index), fixture_index(project_root)
    records = []
    for node in nodes:
        plan = MAPPINGS.get(node["id"])
        if plan is None or plan.title != node["title"]:
            plan = Mapping(node["title"], "待确认", (), note="无已核对映射，或相同 ID 的节点标题已变化。")
        targets = [index.reference(reference) for reference in plan.targets]
        tests, cases = test_evidence(plan, index, fixtures)
        prompt_refs = [{"key": key, **prompts.get(key, {"system_chars": None, "path": None})} for key in plan.prompts]
        unavailable = [item["reference"] for item in targets if not item["verified"]]
        available = all(item["system_chars"] is not None for item in prompt_refs)
        records.append({**node, "disposition": "待确认" if unavailable or not available else plan.disposition,
                        "targets": targets, "missing_targets": unavailable, "prompts": prompt_refs,
                        "tool_dependencies": [index.reference(reference) for reference in TOOLS.get(node["id"], "").split()],
                        "after_system_chars": sum(item["system_chars"] for item in prompt_refs) if available else None,
                        "test_references": tests, "golden_references": cases,
                        "case_status": "静态关联存在；本次未执行" if cases else "未找到可证明的逐节点黄金集关联",
                        "owner": "未指定业务负责人", "note": plan.note,
                        "successors": [edge for edge in edges if edge["source"] == node["id"]]})
    revision = subprocess.run(["git", "-C", str(project_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    mapped_prompts = {prompt["key"] for record in records for prompt in record["prompts"]}
    gaps = [
        {"kind": "legacy_monitor_ui_boundary", "node_id": "1755075477466", "detail": "Dify 专属输入监控调用已明确退役并由原生审计替代；Java 旧 Dify 监控 UI 的 LangGraph 详情展示不是本次已实现承诺，若需要属于后续外部监控集成。"},
        {"kind": "missing_schema_artifact", "detail": "slot_schema.json 的 50 字段附件未提供；以实际 Java/Pydantic 契约为核对来源，不编造字段总数。"},
        {"kind": "acceptance_pending", "detail": "逐节点运行 trace、业务等价、388 条与性能仍需用户统一验收，静态节点表不能替代。"},
    ]
    fast_query = "app/nodes/fast_query.py"
    if (project_root / fast_query).is_file():
        text = index.read(fast_query)
        if "elif code == 500:" in text and "reply = _SERVICE_UNAVAILABLE" in text:
            gaps.append({"kind": "backend_reply_override", "source": fast_query + ":quick_inquiry", "detail": "快速询价 code=500 分支仍使用固定文本覆盖后端 msg；与原样透传约束需要收口。"})
        if "logger.warning(" in text and re.search(r'\(rfq\.get\("raw_response"\) or ""\)\s*\[:', text):
            gaps.append({"kind": "raw_response_logging", "source": fast_query + ":quick_inquiry", "detail": "快速询价仍记录 raw_response 片段；需确认该日志经过统一脱敏。"})
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "project_root": str(project_root), "git_revision": revision,
        "source": {"dsl_path": str(dsl), "sha256": hashlib.sha256(dsl.read_bytes()).hexdigest(),
                   "kind": "local_snapshot_only", "online_version_verified": False},
        "counts": {"nodes": len(nodes), "edges": len(edges), "original_types": dict(Counter(node["original_type"] for node in nodes)),
                   "dispositions": dict(Counter(node["disposition"] for node in records)),
                   "fixture_cases": len({(item["path"], item["line"]) for item in fixtures}), "fixture_turns": len(fixtures),
                   "nodes_with_static_case_association": sum(bool(node["golden_references"]) for node in records)},
        "prompt_measurement": {"unit": "Unicode characters in static system templates; not tokens, runtime payload or latency",
                               "old_main_llm_system_total": sum(node["before_system_chars"] for node in nodes if node["original_type"] == "llm"),
                               "current_mapped_unique_system_total": sum(prompts[key]["system_chars"] or 0 for key in mapped_prompts if key in prompts),
                               "current_mapped_unique_prompts": len(mapped_prompts),
                               "extra_registered_prompts": {key: value for key, value in prompts.items() if key not in mapped_prompts},
                               "exclusions": ["old Code-generated prompt fragments", "runtime injected values", "Pydantic/function schemas", "nested Dify tool workflows", "model tokenization"]},
        "schema_sources": schema_sources(index, java_root), "contract_gaps": gaps, "nodes": records, "edges": edges,
        "audit_retirement": {"node_id": "1755075477466", "decision": "retire_dify_only_side_effect_replace_native_audit",
                             "java_evidence": audit_retirement_evidence(java_root),
                             "limits": ["不调用旧 HTTP 端点、不发送 MQ、不伪造 Dify app/workflow/run ID。", "checkpoint 依赖启用 MySQL saver；消息快照依赖幂等存储；节点审计写失败按现有告警处理。", "durability=exit 不是对超时尚未落盘部分的完整保存保证；Langfuse 依赖配置和成功写入。", "业务 API/机器人响应可切换，不代表 Java 旧 Dify 监控页面自动等价。"]},
        "limits": ["源码对应不等于业务等价；本次未调用模型、后端或黄金集。", "目标函数存在不等于所有分支运行可达；具体调用链仍需相应图测试和真实 trace。",
                   "LLM+Code 表示原始候选/意图保留模型；不能说整条业务流无模型。", "合并说明结构变化；0 字符只表示本节点不再有本地提示资产，不表示外部工具不含模型。",
                   "负责人没有业务授权记录，统一标未指定。", "当前文件逐文件带 hash；主代理并行变更时请在最终集成后重新生成。"],
    }
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    output_prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_prefix.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    logger.info("migration_inventory nodes=%s edges=%s output=%s", len(nodes), len(edges), output_prefix)
    return report


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _source_link(root: str, item: dict[str, Any]) -> str:
    if not item.get("verified"):
        return f"待确认 `{item.get('reference') or item['path']}`"
    path = str(Path(root) / item["path"])
    line = item.get("line", 1)
    return f"[{item.get('symbol') or item['path']}]({path}:{line})"


def render_markdown(report: dict[str, Any]) -> str:
    counts, measure = report["counts"], report["prompt_measurement"]
    lines = ["# Dify → LangGraph 节点迁移证据", "", f"生成时间：{report['generated_at']}；当前 Git HEAD：`{report['git_revision']}`。",
             "本文件是源码盘点，不是验收通过报告。业务实现由各节点链接核对，最终回归由用户统一执行。", "",
             f"实际本地 DSL：**{counts['nodes']} 节点 / {counts['edges']} 连线**，不是规范旧口径的 72 节点。",
             f"源：`{report['source']['dsl_path']}`；SHA-256：`{report['source']['sha256']}`。未访问或确认线上 Dify 版本。",
             "只导出 ID、标题、类型、连线及文本长度；不复制 DSL 的环境变量、密钥、URL、Code 或 Prompt 正文。", "",
             f"原始类型：`{json.dumps(counts['original_types'], ensure_ascii=False)}`。",
             f"目标归属：`{json.dumps(counts['dispositions'], ensure_ascii=False)}`。", "",
             f"原主干 LLM system 静态字符合计 **{measure['old_main_llm_system_total']:,}**；对应当前 {measure['current_mapped_unique_prompts']} 个去重 PromptSpec system 资产合计 **{measure['current_mapped_unique_system_total']:,}**。",
             "该比较不含旧 Code 生成的公共片段、运行时变量、结构化输出 Schema、嵌套工具工作流；不是 token 数或性能结论。", "",
             "## 逐节点对应", "",
             "目标归属 Code 表示原功能由代码处理；LLM+Code 表示模型仍提取候选或识别意图，最终值由代码处理；合并表示多个旧节点共享现有实现。未证实删除的功能不标删除。",
             "每行的负责人均为“未指定业务负责人”。用例关联依据和完整测试函数、文件哈希、原始连线见同名 JSON；未匹配 case 的节点不能当作已验证。", "",
             "| Dify ID / 节点 | 原类型 | 目标归属 | 当前符号 | 依赖工具/模型工厂 | system 字符 前→后 | 可核对 case | 说明 |",
             "|---|---|---|---|---|---:|---|---|"]
    for node in report["nodes"]:
        targets = "<br>".join(_source_link(report["project_root"], target) for target in node["targets"]) or "待确认"
        tools = "<br>".join(_source_link(report["project_root"], target) for target in node["tool_dependencies"]) or "无独立外部工具 / 合并后由调用边界统一执行"
        cases = list(dict.fromkeys(f"{item['case_id']}#t{item['turn']}" for item in node["golden_references"]))
        case_text = ", ".join(cases[:4]) + (f"；另 {len(cases) - 4} 项见 JSON" if len(cases) > 4 else "") if cases else "待确认（无逐节点静态关联）"
        lines.append(f"| `{node['id']}` {_escape(node['title'])} | {node['original_type']} | {node['disposition']} | {targets} | {tools} | {node['before_system_chars']} → {node['after_system_chars'] if node['after_system_chars'] is not None else '未知'} | {_escape(case_text)} | {_escape(node['note'])} |")
    lines += ["", "## 未在主干节点一一对应的当前提示资产", "",
              "这些是额外工具或新编排阶段，不能用主干 DSL 的字符数作为其直接对照。get_qwen_* 是历史工厂命名，不代表当前配置的模型名称或 thinking 开关。", "", "| PromptSpec | system 字符 | 注册位置 |", "|---|---:|---|"]
    for key, value in measure["extra_registered_prompts"].items():
        lines.append(f"| `{key}` | {value['system_chars']} | `{value['registration']}` |")
    lines += ["", "## Schema 与验收证据边界", "", report["schema_sources"]["note"], "",
              "| 当前契约来源 | 核对状态 |", "|---|---|"]
    for item in report["schema_sources"]["python"]:
        lines.append(f"| {_source_link(report['project_root'], item)} | {'符号存在' if item['verified'] else '待确认'} |")
    for item in report["schema_sources"]["java"]:
        lines.append(f"| `{item['class']}`：{'；'.join(item['paths'])} | {'唯一文件，哈希见 JSON' if item['unique'] else '待确认'} |")
    lines += ["", f"当前显式 categories：{counts['fixture_cases']} case / {counts['fixture_turns']} turn。未并入 unified。",
              "case 关联仅采用该轮明确 expected.product_type / intent，或相关测试源码中已有的完整 case_id 字面量；不依靠猜测补全。",
              "节点迁移还需要逐节点黄金集 trace、边界错误与性能实测。输出预算、会话过期、录制回放、多指令和不确定写入恢复是横切能力，不能靠本主干节点表证明完成。", ""]
    lines += ["", "## Dify 输入监控调用退役依据", "",
              "节点 `1755075477466` 的旧 HTTP 副作用明确退役。Java 实现将输入落入 Dify 专属表并触发异步消费者，消费者固定按 Dify 身份读取运行和节点详情；LangGraph 的真实运行标识不能满足这个契约。", "",
              "LangGraph 使用当前共享 MySQL checkpoint 保存状态，用 langgraph_message_log 保存消息和真实响应快照，用 langgraph_node_trace / Langfuse 记录实际执行。它们是审计职责替代，不是向旧接口提供伪造 ID。", "",
              "| Java 权威依据 | 核对结论 |", "|---|---|"]
    for item in report["audit_retirement"]["java_evidence"]:
        link = f"[{item['java_relative_path']}]({item['path']}:{item['lines'][0]})" if item["verified"] else f"`{item['java_relative_path']}`（本次未核对或定位不唯一）"
        lines.append(f"| {link} | {_escape(item['meaning'])} |")
    lines += [""]
    lines.extend(f"- {limit}" for limit in report["audit_retirement"]["limits"])
    lines += ["", "## 仍需确认的契约差异", ""]
    lines.extend(f"- {gap['detail']}" for gap in report["contract_gaps"])
    lines += ["", f"{counts['nodes_with_static_case_association']} / {counts['nodes']} 个旧节点找到可证明的静态 case 关联；其余不代表没有测试，但尚无逐节点黄金集 trace 证据。", ""]
    lines.extend(f"- {limit}" for limit in report["limits"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsl", type=Path, required=True, help="Read-only local Dify workflow snapshot")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--java-root", type=Path)
    parser.add_argument("--out-prefix", type=Path, default=Path("tmp/node-migration-20260918"))
    args = parser.parse_args()
    root = args.project_root.resolve()
    output = args.out_prefix if args.out_prefix.is_absolute() else root / args.out_prefix
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    generate(root, args.dsl.resolve(), output, args.java_root.resolve() if args.java_root else None)


if __name__ == "__main__":
    main()
