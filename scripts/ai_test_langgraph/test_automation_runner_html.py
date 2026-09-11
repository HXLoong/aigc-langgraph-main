from __future__ import annotations

import re
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LANGGRAPH_HTML = SCRIPT_DIR / "automation_runner.html"


def style_block(document: str) -> str:
    match = re.search(r"<style>(.*?)</style>", document, re.DOTALL)
    if match is None:
        raise AssertionError("页面缺少 style 块")
    return match.group(1)


class AutomationRunnerHtmlContractTest(unittest.TestCase):
    def test_contains_styles_and_primary_controls(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        self.assertTrue(style_block(langgraph).strip())
        self.assertIn('<form id="runner-form" class="settings-form">', langgraph)
        for marker in (
            'id="chat-workspace"',
            'id="chat-composer"',
            'data-chat-action="quote"',
            'api("/api/chat/messages"',
            'id="start-queue-button"',
            'id="task-queue"',
            'id="case-log-dialog"',
            'turn.outputs?.trace_url',
            'result.trace_url',
            '查看 LangFuse Trace',
            'data-action="pause"',
            'makeButton("恢复", "resume"',
            'makeButton("↑ 前移", "move-up"',
            'makeButton("删除记录", "delete"',
        ):
            self.assertIn(marker, langgraph)

    def test_queue_refresh_preserves_page_scroll_position(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        render_queue = re.search(
            r"function renderQueue\(payload\) \{(?P<body>.*?)\n    \}",
            langgraph,
            re.DOTALL,
        )
        self.assertIsNotNone(render_queue)
        body = render_queue.group("body")
        self.assertIn("const pageScroll = {left: window.scrollX, top: window.scrollY};", body)
        self.assertIn("window.scrollTo(pageScroll.left, pageScroll.top);", body)


if __name__ == "__main__":
    unittest.main()
