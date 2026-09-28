"""统一处理附件边界：图片明确拒绝，Excel 全部读取后再进入唯一模型请求。"""
from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.parsing.attachments import fetch_file, read_excel


def _extension(file: dict[str, Any]) -> str:
    """兼容带点扩展名及只有 URL 的文件对象。"""
    value = file.get("extension") or PurePosixPath(urlsplit(str(file.get("url") or file.get("remote_url") or "")).path).suffix
    return str(value).lower().lstrip(".")


@safe_node
async def prepare_input(state: AgentState) -> dict[str, Any]:
    """先检查整批类型，再读取整批内容；任何分支都不静默忽略附件。"""
    files = state.get("input_files") or []
    # 1. 图片检查覆盖整批混合输入，并且发生在任何文件下载之前。
    if any(str(file.get("type") or "").lower() == "image"
           or str(file.get("mime_type") or "").lower().startswith("image/")
           or _extension(file) in {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff"}
           for file in files):
        return {"reply_text": "当前暂不处理图片，请改用文本或 Excel 后重新发送。"}
    if any(_extension(file) not in {"xlsx", "xlsm", "xltx"}
           and file.get("mime_type") != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
           for file in files):
        return {"reply_text": "附件格式暂不支持，请改用文本或 .xlsx 格式的 Excel。"}
    if files and (state.get("fast_query") == "1" or state.get("existing_command") == "1"):
        return {"reply_text": "附件请通过普通智能指令发送；快速询价和存量查询请使用文本。"}

    # 2. 每份文件保留独立来源；读取期间不调用模型，也不逐行解析业务含义。
    sources: dict[str, str] = {}
    rows: list[str] = []
    for index, file in enumerate(files):
        url = str(file.get("remote_url") or file.get("url") or "")
        if not url:
            return {"reply_text": "Excel 附件缺少可读取地址，请重新发送。"}
        try:
            parsed = await asyncio.to_thread(read_excel, await fetch_file(url), index)
        except (ValueError, OSError) as exc:
            return {"reply_text": f"Excel 内容无法读取：{exc}。请检查并重新发送。"}
        sources.update(parsed.sources)
        rows.extend(parsed.rows)
    if files and not rows:
        return {"reply_text": "Excel 中没有可读取的数据行，请补充后重新发送。"}
    return {"attachment_sources": sources, "attachment_rows": rows,
            "trace": [TraceEntry(node="prepare_input", decision=f"files={len(files)},rows={len(rows)}")]}
