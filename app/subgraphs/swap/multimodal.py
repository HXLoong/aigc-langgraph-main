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

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_structured, get_qwen_vl
from app.prompts import load_prompt, resolve_prompt_version
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
    async with httpx.AsyncClient(timeout=30.0) as client:
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


async def _extract_params(
    prompt_name: str, user_text: str, conversation_id: str | None = None
) -> tuple[SwapPlaceOrderParams, str]:
    """image_extract / excel_extract 共用的参数提取调用(走 _versions.yaml 灰度)。

    返回 (参数, 实际加载的 prompt name)——后者写进 trace（ADR 0003 灰度硬前置）。
    """
    resolved = resolve_prompt_version("swap", prompt_name, conversation_id)
    prompt = load_prompt("swap", resolved)
    llm = get_qwen_structured().with_structured_output(SwapPlaceOrderParams)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_text),
        ]
    )
    return result, resolved


def _params_update(
    params: SwapPlaceOrderParams, node: str, decision: str, prompt_name: str | None = None
) -> dict[str, Any]:
    action = _expected_action(params)
    return {
        "place_params": {
            "expected_action": action,
            "orderList": [item.model_dump() for item in params.order_list],
        },
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

    ocr_prompt = load_prompt(
        "swap", resolve_prompt_version("swap", "image_ocr", state.get("conversation_id"))
    )
    vl = get_qwen_vl()
    content: list[dict[str, Any]] = [{"type": "text", "text": ocr_prompt.system}]
    for u in urls:
        content.append({"type": "image_url", "image_url": {"url": u}})
    ocr_result = await vl.ainvoke([{"role": "user", "content": content}])
    ocr_text = getattr(ocr_result, "content", "") or ""

    user_text = f"图片识别内容:\n{ocr_text}\n\nraw_content: {state.get('raw_text', '') or ''}"
    params, prompt_name = await _extract_params(
        "image_extract", user_text, state.get("conversation_id")
    )
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

    user_text = f"Excel 数据:\n{rows_text}\n\nraw_content: {state.get('raw_text', '') or ''}"
    params, prompt_name = await _extract_params(
        "excel_extract", user_text, state.get("conversation_id")
    )
    return _params_update(params, "swap_excel_order", f"rows={len(rows)}", prompt_name)


__all__ = ["swap_image_order", "swap_excel_order", "parse_excel_rows"]
