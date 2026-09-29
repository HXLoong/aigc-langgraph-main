"""附件必须在唯一模型请求前准备完整，图片和混合输入明确停止。"""
from __future__ import annotations

import importlib
import importlib.util
import io

import openpyxl
import pytest


def _module():
    """附件准备缺失时以明确行为断言报告 RED。"""
    assert importlib.util.find_spec("app.nodes.prepare_input") is not None, "缺少统一附件入口"
    return importlib.import_module("app.nodes.prepare_input")


def _book(symbol: str) -> bytes:
    """建立真实 Excel 字节，校验多文件来源定位。"""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["标的", "名义本金（万元）"])
    sheet.append([symbol, 100])
    buffer = io.BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


@pytest.mark.parametrize("files", [
    [{"type": "image", "url": "http://image.invalid/a.png"}],
    [{"type": "image", "url": "http://image.invalid/a.png"}, {"extension": ".xlsx", "url": "http://book.invalid/a"}],
])
async def test_any_image_stops_before_download_or_model(monkeypatch, files) -> None:
    """含图片时整体拒绝，不只处理剩余文字或 Excel。"""
    module = _module()

    async def forbidden(url):
        """输入类别明确拒绝后不下载附件。"""
        raise AssertionError("不应下载图片或部分文件")

    monkeypatch.setattr(module, "fetch_file", forbidden)
    update = await module.prepare_input({"raw_text": "询价", "input_files": files})
    assert "图片" in update["reply_text"] and "Excel" in update["reply_text"]
    assert not update.get("attachment_sources")


async def test_all_excel_files_read_before_one_parse(monkeypatch) -> None:
    """两份工作簿统一准备，保留原表头单位，代码不把金额转换为元。"""
    module = _module()
    content = {"http://book.invalid/1": _book("茅台"), "http://book.invalid/2": _book("腾讯")}

    async def fetch(url):
        """只替换下载边界，Excel 解析使用真实 openpyxl。"""
        return content[url]

    monkeypatch.setattr(module, "fetch_file", fetch)
    update = await module.prepare_input({"raw_text": "全部询价", "input_files": [
        {"extension": ".xlsx", "url": url} for url in content
    ]})
    assert update.get("error") is None and not update.get("reply_text")
    assert update["attachment_rows"] == ["file:0:sheet:0:row:2", "file:1:sheet:0:row:2"]
    assert update["attachment_sources"]["file:0:sheet:0:row:2:column:B"] == "名义本金（万元）: 100"
    assert "腾讯" in update["attachment_sources"]["file:1:sheet:0:row:2"]


async def test_rejected_attachment_still_persists_message_intent(monkeypatch):
    """附件拒绝不执行业务，但回复前仍完成普通消息的 Java 意图写回。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.graph.main import build_main_graph

    write_intent = AsyncMock()
    forbidden = AsyncMock(side_effect=AssertionError("附件拒绝不能执行业务"))
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", forbidden)
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", forbidden)
    monkeypatch.setattr("app.nodes.persist.write_node_trace", AsyncMock())
    state = await build_main_graph(message_client_factory=lambda: SimpleNamespace(set_intent=write_intent)).ainvoke({
        "raw_text": "见图片", "conversation_id": "c", "message_id": 1,
        "input_files": [{"type": "image", "url": "http://unused/image.png"}],
    })
    assert "图片" in state["reply_text"]
    write_intent.assert_awaited_once()
    assert write_intent.await_args.args[0].intent == "unknown_intent"
    forbidden.assert_not_called()
