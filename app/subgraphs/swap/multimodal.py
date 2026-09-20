"""图片/Excel 转写证据 → 原文候选 → Code 归一化；写入仍由 submit 完成。"""
from __future__ import annotations

import asyncio
import io
from typing import Any

import httpx
import openpyxl
from pydantic import BaseModel

from app.config import get_settings
from app.extraction.candidates import evidence_sources, verify_candidates
from app.graph.business_params import validated_place_params
from app.graph.retry import io_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_structured, get_qwen_vl
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.multimodal_evidence import (
    ImageTranscription,
    excel_evidence_rows,
    lock_attachment_bindings,
    normalize_attachment_candidates,
)
from app.subgraphs.swap.place_order import (
    CANDIDATE_MODEL,
    _expected_action,
)


def parse_excel_rows(content: bytes) -> list[dict[str, Any]]:
    """保留旧工具接口：解析首个 sheet，产品列改名交易对手。"""
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    try:
        sheet = workbook.active
        if sheet is None:
            return []
        rows_iter = sheet.iter_rows(values_only=True)
        headers = [str(h) if h is not None else "" for h in next(rows_iter, ())]
        headers = ["交易对手" if h == "产品" else h for h in headers]
        return [dict(zip(headers, row, strict=False))
                for row in rows_iter if any(value is not None for value in row)]
    finally:
        workbook.close()


async def _fetch_bytes(url: str) -> bytes:
    seconds = get_settings().multimodal_fetch_timeout_seconds
    async with asyncio.timeout(seconds), httpx.AsyncClient(timeout=seconds) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _image_urls(files: list[dict[str, Any]]) -> list[str]:
    return [str(url) for file in files
            if (url := file.get("remote_url") or file.get("url") or file.get("base64"))]


def _user_from_state(state: AgentState) -> str:
    return blocks.source_payload(state)


IMAGE_OCR_SPEC = register(PromptSpec(
    category="swap", name="image_ocr", output_model=ImageTranscription,
    inputs=("input_files", "conversation_id"), user_builder=lambda state: "", gray=True,
))
IMAGE_EXTRACT_SPEC = register(PromptSpec(
    category="swap", name="image_extract", output_model=CANDIDATE_MODEL,
    inputs=("conversation_id", "raw_text", "quote_content", "history_messages"),
    user_builder=_user_from_state, gray=True,
))
EXCEL_EXTRACT_SPEC = register(PromptSpec(
    category="swap", name="excel_extract", output_model=CANDIDATE_MODEL,
    inputs=("conversation_id", "raw_text", "quote_content", "history_messages"),
    user_builder=_user_from_state, gray=True,
))


async def _extract_candidates(
    spec: PromptSpec, state: AgentState, attachments: dict[str, str],
) -> tuple[BaseModel, str]:
    system, prompt_name = spec.render_system(state)
    sources = evidence_sources(state, attachments)
    llm = get_qwen_structured().with_structured_output(CANDIDATE_MODEL)
    result = CANDIDATE_MODEL.model_validate(await llm.ainvoke([
        ("system", system),
        ("user", blocks.source_payload(state, attachments=attachments)),
    ]))
    verify_candidates(result, sources)
    # Every row must be grounded in this attachment, not a duplicated instruction from raw/history.
    for row in result.model_dump(by_alias=True).get("orderList") or []:
        if not any(cell and cell.get("origin") == "attachment" for cell in row.values()):
            raise ValueError("附件订单缺少对应附件证据")
    return result, prompt_name


async def _params_update(
    orders: list[dict[str, Any]], attachments: dict[str, str], state: AgentState,
    node: str, decision: str, prompt_names: list[str], *, ocr_prompt_name: str | None = None,
) -> dict[str, Any]:
    if not orders:
        raise ValueError("附件中未识别到有效订单，请提供清晰的交易信息")
    candidates = CANDIDATE_MODEL.model_validate({"orderList": orders})
    params, records = normalize_attachment_candidates(candidates, evidence_sources(state, attachments))
    params, records = lock_attachment_bindings(
        params, records, state.get("swap_counterparties") or [],
    )
    return {
        "expected_action": _expected_action(params),
        "place_params": validated_place_params(orderList=[item.model_dump() for item in params.order_list]),
        "field_records": records,
        "intent": "place_order_request",
        "trace": [TraceEntry(node=node, decision=decision, llm_output={
            "prompt_name": prompt_names[0], "prompt_names": list(dict.fromkeys(prompt_names)),
            "ocr_prompt_name": ocr_prompt_name,
            "attachment_references": list(attachments),
        })],
    }


@io_node
async def swap_image_order(state: AgentState) -> dict[str, Any]:
    """每张图片独立转写，来源引用不可跨图漂移；OCR 不负责代码/账户映射。"""
    files = [(index, file) for index, file in enumerate(state.get("input_files") or [])
             if str(file.get("type", "")).lower() == "image"]
    if not files:
        raise ValueError("互换-图片链:无可用图片文件")
    ocr_system, ocr_prompt_name = IMAGE_OCR_SPEC.render_system(state)
    vl = get_qwen_vl().with_structured_output(ImageTranscription)
    attachments, orders, prompt_names = {}, [], []
    for index, file in files:
        urls = _image_urls([file])
        if not urls:
            raise ValueError("互换-图片链:图片缺少可用地址")
        transcription = ImageTranscription.model_validate(await vl.ainvoke([{
            "role": "user", "content": [
                {"type": "text", "text": ocr_system},
                {"type": "image_url", "image_url": {"url": urls[0]}},
            ],
        }]))
        reference = f"file:{index}:image"
        source = {reference: transcription.text}
        extracted, prompt_name = await _extract_candidates(IMAGE_EXTRACT_SPEC, state, source)
        attachments.update(source)
        orders.extend(extracted.model_dump(by_alias=True)["orderList"])
        prompt_names.append(prompt_name)
    return await _params_update(
        orders, attachments, state, "swap_image_order", f"images={len(files)}", prompt_names,
        ocr_prompt_name=ocr_prompt_name,
    )


@io_node
async def swap_excel_order(state: AgentState) -> dict[str, Any]:
    """逐文件、工作表和行抽取，保留单元格引用并限制单次模型输出规模。"""
    files = [(index, file) for index, file in enumerate(state.get("input_files") or [])
             if str(file.get("type", "")).lower() != "image"]
    if not files:
        raise ValueError("互换-Excel 链:无可用 Excel 文件")
    attachments, orders, prompt_names = {}, [], []
    row_count = 0
    for index, file in files:
        url = file.get("remote_url") or file.get("url")
        if not url:
            raise ValueError("互换-Excel 链:文件缺少 remote_url/url")
        rows = await asyncio.to_thread(excel_evidence_rows, await _fetch_bytes(url), index)
        for row in rows:
            extracted, prompt_name = await _extract_candidates(EXCEL_EXTRACT_SPEC, state, row.sources)
            extracted_orders = extracted.model_dump(by_alias=True)["orderList"]
            if not extracted_orders:
                raise ValueError("Excel 非空行未识别到订单，已停止提交以避免漏单")
            attachments.update(row.sources)
            orders.extend(extracted_orders)
            prompt_names.append(prompt_name)
            row_count += 1
    return await _params_update(
        orders, attachments, state, "swap_excel_order", f"rows={row_count}", prompt_names,
    )


__all__ = ["swap_image_order", "swap_excel_order", "parse_excel_rows"]
