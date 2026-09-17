"""swap 图片/Excel 多模态下单链(DSL v2 互换-图片 / 互换-Excel 分支)。

对照源(dify/yaml/主干工作流.yml):
- 互换-图片:互换-图片识别[VL llm] → 图片-互换-请求下单参数解析[llm]
- 互换-Excel:解析Excel[code] → Excel-互换-请求下单参数解析[llm]
两链输出与文本链共同汇入 模型数据聚合 → 前置清洗 → 互换开仓(submit 节点复用)。

提示词:swap/image_ocr.md(VL 识别)、swap/image_extract.md、swap/excel_extract.md。
Excel 解析移植自「解析Excel」code 节点:下载 → openpyxl → "产品"列改名"交易对手"。
"""
from __future__ import annotations

import asyncio
import io
import json
from typing import Any

import httpx
import openpyxl

from app.config import get_settings
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_structured, get_qwen_vl
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.place_order import _expected_action


def parse_excel_rows(content: bytes) -> list[dict[str, Any]]:
    """openpyxl 解析首个 sheet;"产品"列名改为"交易对手"(对照 DSL code 节点)。"""
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        headers = [str(h) if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        return []
    headers = ["交易对手" if h == "产品" else h for h in headers]
    result: list[dict[str, Any]] = []
    for row in rows_iter:
        if all(v is None for v in row):
            continue
        result.append(dict(zip(headers, row, strict=False)))
    return result


async def _fetch_bytes(url: str) -> bytes:
    """下载远端文件(测试 patch 此名)。"""
    async with httpx.AsyncClient(timeout=get_settings().multimodal_fetch_timeout_seconds) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _image_urls(files: list[dict[str, Any]]) -> list[str]:
    urls = []
    for f in files:
        u = f.get("remote_url") or f.get("url") or f.get("base64")
        if u:
            urls.append(u)
    return urls


def _extract_user(title: str, runtime_text: str, raw_text: str) -> str:
    """图片 / Excel 提取链共用的 user 消息模板（运行时块 + raw_content）。"""
    return f"{title}:\n{runtime_text}\n\nraw_content: {raw_text}"


def _image_extract_user_from_state(state: AgentState) -> str:
    """注册契约的 state-only 重建（OCR 文本为运行时数据，节点注入；此处为空形态）。"""
    return _extract_user("图片识别内容", "", state.get("raw_text", "") or "")


def _excel_extract_user_from_state(state: AgentState) -> str:
    """注册契约的 state-only 重建（Excel 行数据为运行时数据，节点注入；此处为空形态）。"""
    return _extract_user("Excel 数据", "", state.get("raw_text", "") or "")


def _ocr_user_from_state(state: AgentState) -> str:
    """VL 链无文本 user 段（消息为 system 文本 + image_url 列表，由节点组装）。"""
    return ""


IMAGE_OCR_SPEC = register(PromptSpec(
    category="swap",
    name="image_ocr",
    output_model=None,
    inputs=("conversation_id", "swap_counterparties"),
    user_builder=_ocr_user_from_state,
    injects={
        # Dify code 节点 json.dumps(optionList…) 同口径（评估 C-27）
        "{{#1772773805306.optionListStr#}}": lambda s: blocks.json_list(s.get("swap_counterparties")),
    },
    gray=True,
))

IMAGE_EXTRACT_SPEC = register(PromptSpec(
    category="swap",
    name="image_extract",
    output_model=SwapPlaceOrderParams,
    inputs=("conversation_id", "raw_text"),
    user_builder=_image_extract_user_from_state,
    gray=True,
))

EXCEL_EXTRACT_SPEC = register(PromptSpec(
    category="swap",
    name="excel_extract",
    output_model=SwapPlaceOrderParams,
    inputs=("conversation_id", "raw_text"),
    user_builder=_excel_extract_user_from_state,
    gray=True,
))


async def _extract_params(
    spec: PromptSpec, user_text: str, state: AgentState
) -> tuple[SwapPlaceOrderParams, str]:
    """image_extract / excel_extract 共用的参数提取调用（spec 负责灰度解析与 system 渲染）。

    返回 (参数, 实际加载的 prompt name)——后者写进 trace（ADR 0003 灰度硬前置）。
    """
    system, prompt_name = spec.render_system(state)
    llm = get_qwen_structured().with_structured_output(SwapPlaceOrderParams)
    result: Any = await llm.ainvoke(
        [
            ("system", system),
            ("user", user_text),
        ]
    )
    return result, prompt_name


def _params_update(
    params: SwapPlaceOrderParams, node: str, decision: str, prompt_name: str | None = None
) -> dict[str, Any]:
    action = _expected_action(params)
    return {
        "expected_action": action,
        "place_params": {"orderList": [item.model_dump() for item in params.order_list]},
        "intent": "place_order_request",
        "trace": [
            TraceEntry(node=node, decision=decision, llm_output={"prompt_name": prompt_name})
        ],
    }


@safe_node
async def swap_image_order(state: AgentState) -> dict[str, Any]:
    """互换-图片链:VL OCR → 参数提取 → place_params(提交由 submit 节点完成)。"""
    files = [f for f in (state.get("input_files") or []) if str(f.get("type", "")).lower() == "image"]
    urls = _image_urls(files)
    if not urls:
        raise ValueError("互换-图片链:无可用图片文件")

    # Dify 原 system 的 {{#1772773805306.optionListStr#}} 由 code 节点 json.dumps 注入；
    # 互换图片链按同口径渲染（SPEC.injects，ADR 0022 D5，评估 C-27）
    ocr_system, _ocr_prompt_name = IMAGE_OCR_SPEC.render_system(state)
    vl = get_qwen_vl()
    content: list[dict[str, Any]] = [{"type": "text", "text": ocr_system}]
    for u in urls:
        content.append({"type": "image_url", "image_url": {"url": u}})
    ocr_result = await vl.ainvoke([{"role": "user", "content": content}])
    ocr_text = getattr(ocr_result, "content", "") or ""

    user_text = _extract_user("图片识别内容", ocr_text, state.get("raw_text", "") or "")
    params, prompt_name = await _extract_params(IMAGE_EXTRACT_SPEC, user_text, state)
    return _params_update(params, "swap_image_order", f"images={len(urls)}", prompt_name)


@safe_node
async def swap_excel_order(state: AgentState) -> dict[str, Any]:
    """互换-Excel 链:下载解析(产品→交易对手)→ 参数提取 → place_params。"""
    files = state.get("input_files") or []
    url = None
    for f in files:
        u = f.get("remote_url") or f.get("url")
        if u:
            url = u
            break
    if not url:
        raise ValueError("互换-Excel 链:文件缺少 remote_url/url")

    content = await _fetch_bytes(url)
    rows = await asyncio.to_thread(parse_excel_rows, content)
    rows_text = json.dumps(rows, ensure_ascii=False, default=str)

    user_text = _extract_user("Excel 数据", rows_text, state.get("raw_text", "") or "")
    params, prompt_name = await _extract_params(EXCEL_EXTRACT_SPEC, user_text, state)
    return _params_update(params, "swap_excel_order", f"rows={len(rows)}", prompt_name)


__all__ = ["swap_image_order", "swap_excel_order", "parse_excel_rows"]
