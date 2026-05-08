"""互换子图（完整实现）。

对应 Dify：
- `互换工具.yml` (4 节点)
- 主工作流中的互换相关节点群：
  * 互换参数聚合
  * 互换-图片识别（VL 模型）
  * 解析Excel
  * Excel-互换-请求下单参数解析
  * 图片-互换-请求下单参数解析
  * 互换-节点-意图识别
  * 互换-节点-下单 / 确认下单 / 撤单 / 确认撤单 / 确认改单 / 查询订单
  * 互换-提取标的代码名称
  * 将提取出的标的列表拼接原数据
  * 标的智能化识别（tool call）

设计要点：
1. 三种入口：文本 / Excel / 图片，进入后统一汇聚到意图分类
2. 标的识别统一走 ticker_subgraph (Agent)
3. 六种意图对应两类参数提取（下单 / 订单ID）
4. 最终统一调用 otc_backend.swap_operate
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.nodes.common import safe_node
from app.state import AgentState, preview
from app.subgraphs.swap_models import (
    SwapIntentOutput,
    SwapOrderIdOutput,
    SwapPlaceOrderOutput,
)
from app.tools.otc_backend import OtcBackendClient

logger = logging.getLogger(__name__)


# ==============================================================
# 模态分发（文本 / Excel / 图片）
# ==============================================================
@safe_node
async def dispatch_modality(state: AgentState) -> dict[str, Any]:
    """判断用户输入的形态。"""
    wx = state["wechat_input"]
    attachments = wx.get("attachments") or []
    if not attachments:
        modality = "text"
    else:
        first = attachments[0]
        type_ = (first.get("type") or "").lower()
        filename = (first.get("filename") or first.get("url") or "").lower()
        if "xlsx" in filename or "xls" in filename or type_ in {"excel", "xlsx"}:
            modality = "excel"
        elif type_ in {"image", "jpg", "jpeg", "png"} or any(
            filename.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")
        ):
            modality = "image"
        else:
            modality = "text"

    return {
        "trace": [{"node": "dispatch_modality", "decision": modality}],
        "modality": modality,
    }


def route_by_modality(state: AgentState) -> str:
    return state.get("modality", "text")


# ==============================================================
# 图片识别（VL OCR）
# ==============================================================
IMAGE_OCR_SYSTEM_PROMPT = """你是专业的金融交易图片文字识别引擎。

## 任务
将交易界面截图中的所有文字准确识别并输出为结构化文本。

## 规则
1. 逐字节精确识别：标点/全半角/特殊符号原样保留
2. 若图中有表格，以 Markdown 表格输出
3. 若图中有多段文字（如"总单" + 明细列表），分段输出并保持顺序
4. 只输出识别结果，不添加任何说明
"""


@safe_node
async def parse_image(state: AgentState) -> dict[str, Any]:
    """VL 模型 OCR：把互换截图还原成文本，写回 raw_content。

    对应 Dify `互换-图片识别` 节点。
    阶段 3 要点：
    1. 从附件下载图片
    2. base64 编码
    3. 调 Qwen VL 模型
    4. OCR 结果拼接到 raw_content 后面，供下游使用
    """
    import base64

    import httpx as _httpx

    from app.llm.clients import get_qwen_vl

    wx = state["wechat_input"]
    attachments = wx.get("attachments") or []
    if not attachments:
        return {"trace": [{"node": "parse_image", "status": "skip",
                           "decision": "no_attachment"}]}

    # 取第一张图片附件
    image_url = None
    for att in attachments:
        type_ = (att.get("type") or "").lower()
        fn = (att.get("filename") or att.get("url") or "").lower()
        if type_.startswith("image") or any(fn.endswith(ext)
                                             for ext in (".jpg", ".jpeg", ".png", ".webp")):
            image_url = att.get("remote_url") or att.get("url")
            break

    if not image_url:
        return {"trace": [{"node": "parse_image", "status": "skip",
                           "decision": "no_image_in_attachments"}]}

    # 下载图片并 base64 编码
    try:
        async with _httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(image_url)
            r.raise_for_status()
            image_b64 = base64.b64encode(r.content).decode()
            mime = "image/jpeg"
            if image_url.lower().endswith(".png"):
                mime = "image/png"
            elif image_url.lower().endswith(".webp"):
                mime = "image/webp"
    except Exception as e:
        return {
            "error": f"图片下载失败: {e}",
            "trace": [{"node": "parse_image", "status": "error", "error": str(e)}],
        }

    # 调 VL 模型（OpenAI 兼容的多模态 content）
    vl = get_qwen_vl()
    try:
        resp = await vl.ainvoke([
            ("system", IMAGE_OCR_SYSTEM_PROMPT),
            ("user", [
                {"type": "text", "text": "请识别这张图中的全部文字。"},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ]),
        ])
        ocr_text = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as e:
        return {
            "error": f"VL 模型调用失败: {e}",
            "trace": [{"node": "parse_image", "status": "error", "error": str(e)}],
        }

    # 把 OCR 结果拼到 raw_content 之后，供下游参数提取使用
    original = wx.get("raw_content", "")
    merged = f"{original}\n\n[图片识别结果]\n{ocr_text}" if original else ocr_text
    new_wx = {**wx, "raw_content": merged}

    return {
        "wechat_input": new_wx,
        "trace": [{"node": "parse_image", "output_preview": preview(ocr_text)}],
    }


# ==============================================================
# Excel 解析
# ==============================================================
@safe_node
async def parse_excel(state: AgentState) -> dict[str, Any]:
    """openpyxl 解析 Excel，把行数据写回 raw_content。

    对应 Dify `解析Excel` 节点。
    列名归一化：`产品` / `产品名称` → `交易对手`（业务口径）
    """
    import io

    import httpx as _httpx
    try:
        import openpyxl
    except ImportError:
        return {
            "error": "未安装 openpyxl，请 pip install openpyxl",
            "trace": [{"node": "parse_excel", "status": "error"}],
        }

    wx = state["wechat_input"]
    attachments = wx.get("attachments") or []

    excel_url = None
    for att in attachments:
        fn = (att.get("filename") or att.get("url") or "").lower()
        if fn.endswith(".xlsx") or fn.endswith(".xls") or \
           (att.get("type") or "").lower() in {"excel", "xlsx"}:
            excel_url = att.get("remote_url") or att.get("url")
            break

    if not excel_url:
        return {"trace": [{"node": "parse_excel", "status": "skip",
                           "decision": "no_excel"}]}

    try:
        async with _httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(excel_url)
            r.raise_for_status()
            wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True)
            ws = wb.active
    except Exception as e:
        return {
            "error": f"Excel 下载/解析失败: {e}",
            "trace": [{"node": "parse_excel", "status": "error", "error": str(e)}],
        }

    # 首行作表头
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {"trace": [{"node": "parse_excel", "status": "skip",
                           "decision": "empty_workbook"}]}

    headers = [str(h or "").strip() for h in rows[0]]
    # 列名归一化：产品/产品名称 → 交易对手
    headers = [
        "交易对手" if h in ("产品", "产品名称") else h
        for h in headers
    ]

    # 拼装结构化文本（每行一个字典的 JSON 字符串）
    lines = []
    for row in rows[1:]:
        obj = {h: v for h, v in zip(headers, row, strict=False) if v is not None}
        if obj:
            lines.append(", ".join(f"{k}={v}" for k, v in obj.items()))

    excel_text = "[Excel 解析结果]\n" + "\n".join(lines)
    original = wx.get("raw_content", "")
    merged = f"{original}\n\n{excel_text}" if original else excel_text
    new_wx = {**wx, "raw_content": merged}

    return {
        "wechat_input": new_wx,
        "trace": [{"node": "parse_excel",
                   "output_preview": f"{len(lines)} rows parsed"}],
    }


# ==============================================================
# 意图分类（使用 Dify 原始提示词）
# ==============================================================
@safe_node
async def classify_intent(state: AgentState) -> dict[str, Any]:
    """互换意图分类。对应 Dify `互换-节点-意图识别`。"""
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    prompt = load_prompt("swap", "intent")

    wx = state["wechat_input"]
    history = state.get("history_messages", [])
    history_str = "\n".join(
        f"[{m.get('role')}] {m.get('content', '')[:200]}" for m in history[-10:]
    )
    bot_names = ", ".join(state.get("bot_name_list", []))

    user_message = f"""raw_content: {wx.get('raw_content', '')}
quote_content: {wx.get('quote_content', '') or '(无)'}
history_query_str: {history_str or '(无)'}
bot_name_list: {bot_names}"""

    llm = get_qwen_standard().with_structured_output(SwapIntentOutput)
    result: SwapIntentOutput = await llm.ainvoke([
        ("system", prompt.system),
        ("user", user_message),
    ])

    logger.info(
        "swap intent=%s confidence=%.2f reason=%s",
        result.type, result.confidence, result.reason,
    )

    return {
        "intent": result.type,
        "trace": [{
            "node": "classify_intent",
            "decision": result.type,
            "output_preview": f"conf={result.confidence:.2f} reason={result.reason}",
        }],
    }


def route_by_intent(state: AgentState) -> str:
    """根据意图路由到对应的参数提取节点。"""
    intent = state.get("intent")
    mapping = {
        "place_order_request": "extract_place_order",
        "confirm_order": "extract_order_id",
        "cancel_order_request": "extract_order_id",
        "confirm_cancel_order": "extract_order_id",
        "confirm_modify_order": "extract_order_id",
        "query_order_status": "extract_order_id",
    }
    return mapping.get(intent, "call_api")


# ==============================================================
# 参数提取 - 下单（使用 Dify 原始提示词，58K 字符）
# ==============================================================
@safe_node
async def extract_place_order(state: AgentState) -> dict[str, Any]:
    """提取下单参数。对应 Dify `互换-节点-下单`。"""
    from app.config import get_settings
    from app.llm.clients import get_qwen_thinking
    from app.prompts import compose_prompt

    version = get_settings().swap_prompt_version
    prompt = compose_prompt("swap", "place_order", version=version)

    wx = state["wechat_input"]
    resolved = state.get("resolved_tickers", [])
    counterparties = state.get("counterparty_list", [])

    resolved_str = "\n".join(
        f"- {t.wind_code} ({t.ins_sht_desc}) family={t.ins_family}"
        for t in resolved
    ) or "(空，需用户补充标的)"
    cp_str = "\n".join(
        f"- id={c.get('id')} name={c.get('shortName')}"
        for c in counterparties[:20]
    )

    # Dify 原提示词使用占位符 `{{#xxx.raw_content#}}` 等
    # 我们把相关变量都拼接到 user message 里，LLM 能自行读取
    user_message = f"""swap_query: {wx.get('raw_content', '')}
raw_content: {wx.get('raw_content', '')}
quote_content: {wx.get('quote_content', '') or '(无)'}

resolved_tickers:
{resolved_str}

counterparty_list:
{cp_str}
"""

    llm = get_qwen_thinking().with_structured_output(SwapPlaceOrderOutput)
    try:
        result: SwapPlaceOrderOutput = await llm.ainvoke([
            ("system", prompt.system),
            ("user", user_message),
        ])
    except Exception as e:
        return {
            "error": f"下单参数解析失败: {e}",
            "order_list": [],
            "trace": [{"node": "extract_place_order", "status": "error",
                       "error": str(e)}],
        }

    order_dicts = [leg.model_dump(exclude_none=True) for leg in result.order_list]
    return {
        "order_list": order_dicts,
        "trace": [{
            "node": "extract_place_order",
            "output_preview": preview(order_dicts),
        }],
    }


# ==============================================================
# 参数提取 - 订单 ID
# ==============================================================
@safe_node
async def extract_order_id(state: AgentState) -> dict[str, Any]:
    """提取单一订单 ID（confirm / cancel / modify / query 共用）。

    对应 Dify `互换-节点-确认下单`、`撤单`、`确认撤单`、`确认改单`、`查询订单`。
    这五个节点在 Dify 中的提示词几乎一致，我们根据 intent 动态选择对应文件，
    既保留 Dify 原始提示词的细节，又避免代码重复。
    """
    from app.llm.clients import get_qwen_standard
    from app.prompts import load_prompt

    # 按意图选择对应的 Dify 提示词
    intent_to_prompt = {
        "confirm_order": "confirm_order",
        "cancel_order_request": "cancel_order",
        "confirm_cancel_order": "confirm_cancel",
        "confirm_modify_order": "confirm_modify",
        "query_order_status": "query_order",
    }
    intent = state.get("intent", "")
    prompt_name = intent_to_prompt.get(intent, "confirm_order")
    prompt = load_prompt("swap", prompt_name)

    wx = state["wechat_input"]
    history = state.get("history_messages", [])
    history_str = "\n".join(
        f"[{m.get('role')}] {m.get('content', '')[:300]}" for m in history[-5:]
    )

    user_message = f"""raw_content: {wx.get('raw_content', '')}
quote_content: {wx.get('quote_content', '') or '(无)'}
history_query_str: {history_str or '(无)'}"""

    llm = get_qwen_standard().with_structured_output(SwapOrderIdOutput)
    try:
        result: SwapOrderIdOutput = await llm.ainvoke([
            ("system", prompt.system),
            ("user", user_message),
        ])
    except Exception as e:
        return {
            "error": f"订单 ID 提取失败: {e}",
            "trace": [{"node": "extract_order_id", "status": "error",
                       "error": str(e)}],
        }

    order_id = result.order_id
    if order_id.startswith("NOT_FOUND"):
        return {
            "error": "未能从输入中识别出订单号，请提供完整订单号（如 H-20260304-ABCD123456）",
            "trace": [{"node": "extract_order_id", "decision": "not_found"}],
        }

    order_list = [{"orderId": order_id, "action": intent}]
    return {
        "order_list": order_list,
        "order_ids": [order_id],
        "trace": [{"node": "extract_order_id",
                   "output_preview": order_id,
                   "decision": f"prompt={prompt_name}"}],
    }


# ==============================================================
# 调用后端 API
# ==============================================================
@safe_node
async def call_swap_api(state: AgentState) -> dict[str, Any]:
    """统一调用 /admin-api/swap-order/operate。对应 Dify 互换工具的 `互换API`。"""
    wx = state["wechat_input"]
    intent = state.get("intent", "unknown")
    order_list = state.get("order_list", [])

    if not order_list and intent != "unknown":
        return {
            "api_code": 400,
            "api_result": "缺少订单参数，无法调用接口",
            "trace": [{"node": "call_swap_api", "status": "skip",
                       "decision": "empty_order_list"}],
        }

    async with OtcBackendClient() as client:
        resp = await client.swap_operate(
            conversation_id=wx.get("conversation_id", ""),
            message_id=wx.get("message_id", ""),
            message_content=wx.get("raw_content", ""),
            raw_content=wx.get("raw_content", ""),
            quote_content=wx.get("quote_content"),
            quote_appinfo=wx.get("quote_appinfo"),
            user_id=wx.get("user_id", ""),
            room_id=wx.get("room_id", ""),
            guid=wx.get("guid", ""),
            type_=intent,
            order_list=order_list,
        )

    return {
        "api_code": resp.get("code"),
        "api_result": resp.get("result"),
        "trace": [{
            "node": "call_swap_api",
            "output_preview": f"code={resp.get('code')} result={preview(resp.get('result'))}",
        }],
    }


# ==============================================================
# 构建子图
# ==============================================================
def build_swap_graph():
    """构建互换子图。

    拓扑：
        START → dispatch_modality
                    ├─ text   → ticker_identify ─┐
                    ├─ excel  → parse_excel  ───→ ticker_identify
                    └─ image  → parse_image  ───→ ticker_identify
                                                  ▼
                                          classify_intent
                                              │
                      ┌────────────┬──────────┼──────────────┐
                      ▼            ▼          ▼              ▼
            extract_place_order  extract_order_id       (其他/兜底)
                      │            │
                      └─────┬──────┘
                            ▼
                       call_swap_api
                            ▼
                           END
    """
    # 延迟导入避免循环
    from app.subgraphs.ticker import build_ticker_graph

    g = StateGraph(AgentState)

    g.add_node("dispatch_modality", dispatch_modality)
    g.add_node("parse_image", parse_image)
    g.add_node("parse_excel", parse_excel)
    g.add_node("ticker_identify", build_ticker_graph().compile())
    g.add_node("classify_intent", classify_intent)
    g.add_node("extract_place_order", extract_place_order)
    g.add_node("extract_order_id", extract_order_id)
    g.add_node("call_swap_api", call_swap_api)

    g.add_edge(START, "dispatch_modality")
    g.add_conditional_edges(
        "dispatch_modality",
        route_by_modality,
        {
            "text": "ticker_identify",
            "excel": "parse_excel",
            "image": "parse_image",
        },
    )
    g.add_edge("parse_excel", "ticker_identify")
    g.add_edge("parse_image", "ticker_identify")
    g.add_edge("ticker_identify", "classify_intent")

    g.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "extract_place_order": "extract_place_order",
            "extract_order_id": "extract_order_id",
            "call_api": "call_swap_api",
        },
    )

    g.add_edge("extract_place_order", "call_swap_api")
    g.add_edge("extract_order_id", "call_swap_api")
    g.add_edge("call_swap_api", END)

    return g
