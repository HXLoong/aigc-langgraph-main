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

    def test_free_chat_outputs_scroll_horizontally(self) -> None:
        styles = style_block(LANGGRAPH_HTML.read_text(encoding="utf-8"))

        self.assertRegex(
            styles,
            r"\.message-outputs\s*\{[^}]*width: 100%;[^}]*overflow-x: auto;"
            r"[^}]*white-space: pre;[^}]*overflow-wrap: normal;",
        )

    def test_case_dialog_contains_node_annotation_workbench(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            'id="case-log-tab"',
            'id="case-node-tab"',
            'id="case-node-panel"',
            'id="node-product-filter"',
            'id="node-annotation-form"',
            'function loadCaseNodes()',
            'function flattenJsonPointers(',
            'node.output_fields',
            '/nodes`',
            '/node-fixtures`',
        ):
            self.assertIn(marker, langgraph)

    def test_node_editor_handles_view_only_and_empty_stable_outputs(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            "node.annotatable !== false",
            "node.annotation_reason",
            'querySelector(\'option[value="fields"]\')',
            'modeSelect.value = hasFieldCandidates ? "fields" : "object";',
        ):
            self.assertIn(marker, langgraph)

    def test_node_field_paths_are_friendly_without_changing_saved_pointer(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        self.assertIn("function formatJsonPointer(pointer)", langgraph)
        self.assertIn("checkbox.dataset.pointer = pointer;", langgraph)
        self.assertIn("path.textContent = formatJsonPointer(pointer);", langgraph)
        self.assertNotIn("path.textContent = pointer;", langgraph)

    def test_node_annotation_groups_fields_and_supports_batch_selection(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            'id="node-field-tools"',
            'id="node-field-search"',
            'id="node-field-selection"',
            'data-node-field-action="stable"',
            'data-node-field-action="all"',
            'data-node-field-action="clear"',
            "function isVolatileAnnotationPointer(pointer)",
            "function annotationFieldGroup(pointer)",
            "function updateNodeFieldSelectionSummary()",
            'details.className = "node-field-group";',
            'summary.className = "node-field-group-summary";',
            "checkbox.checked = (node.output_fields || []).includes(jsonPointerTokens(pointer)[0])",
            'checkbox.dataset.recommended = String(checkbox.checked);',
        ):
            self.assertIn(marker, langgraph)

        styles = style_block(langgraph)
        self.assertRegex(
            styles,
            r"\.node-field-group-body\s*\{[^}]*content-visibility: auto;",
        )

    def test_annotation_can_select_any_observed_output_field(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            'id="node-field-source-hint"',
            'makeLogBlock("实际输出", JSON.stringify(node.output || {}, null, 2), "output-block", true)',
            'const availableOutput = Object.fromEntries(',
            'Object.entries(node.output || {}).filter(([key]) => key !== "trace" && !key.startsWith("_"))',
            'flattenJsonPointers(availableOutput)',
            'checkbox.checked = (node.output_fields || []).includes(jsonPointerTokens(pointer)[0])',
        ):
            self.assertIn(marker, langgraph)

    def test_actual_output_fields_have_inline_selection_synced_to_expected_values(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            "function makeSelectableOutputJson(value)",
            'checkbox.dataset.outputPointer = pointer;',
            'checkbox.setAttribute("aria-label", `选择实际输出字段 ${formatJsonPointer(pointer)}`);',
            'outputBlock.querySelector("pre").replaceWith(makeSelectableOutputJson(node.output || {}));',
            '$("node-output-block").addEventListener("change", (event) => {',
            'fieldCheckbox.checked = outputCheckbox.checked;',
            'function syncNodeOutputFieldCheckboxes()',
            'row.hidden = !checkbox.checked;',
        ):
            self.assertIn(marker, langgraph)

        styles = style_block(langgraph)
        self.assertIn(".node-output-json-row", styles)

    def test_node_editor_does_not_use_removed_group_index(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")
        render_node_editor = re.search(
            r"function renderNodeEditor\(node\) \{(?P<body>.*?)\n    \}",
            langgraph,
            re.DOTALL,
        )

        self.assertIsNotNone(render_node_editor)
        self.assertNotIn("groupIndex", render_node_editor.group("body"))
        self.assertIn(
            "details.open = Boolean(groupBody.querySelector('input[type=\"checkbox\"]:checked'));",
            render_node_editor.group("body"),
        )

    def test_node_input_and_output_can_open_independent_large_json_view(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            'id="node-json-dialog"',
            'id="node-json-title"',
            'id="node-json-content"',
            'data-close-dialog="node-json-dialog"',
            'function openNodeJsonDialog(label, value)',
            'button.textContent = "放大";',
            'button.setAttribute("aria-label", `放大查看${label}`);',
            'makeLogBlock("节点输入", JSON.stringify(node.input || {}, null, 2), "input-block", true)',
            'makeLogBlock("实际输出", JSON.stringify(node.output || {}, null, 2), "output-block", true)',
        ):
            self.assertIn(marker, langgraph)

        styles = style_block(langgraph)
        self.assertRegex(styles, r"#node-json-dialog\s*\{[^}]*width: min\(1600px,")
        self.assertRegex(styles, r"#node-json-content\s*\{[^}]*overflow: auto;")

    def test_node_list_omits_secondary_metadata(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")
        render_node_list = re.search(
            r"function renderNodeList\(\) \{(?P<body>.*?)\n    \}",
            langgraph,
            re.DOTALL,
        )

        self.assertIsNotNone(render_node_list)
        body = render_node_list.group("body")
        self.assertIn("title.textContent = `第 ${node.turn} 轮 · ${node.name}`;", body)
        self.assertNotIn('document.createElement("small")', body)
        self.assertNotIn('node.replayable ? "可回归"', body)

    def test_node_workbench_uses_remaining_height_below_toolbar(self) -> None:
        styles = style_block(LANGGRAPH_HTML.read_text(encoding="utf-8"))
        node_panel = re.search(r"\.node-panel\s*\{(?P<body>[^}]*)\}", styles)
        node_workbench = re.search(r"\.node-workbench\s*\{(?P<body>[^}]*)\}", styles)

        self.assertIsNotNone(node_panel)
        self.assertIsNotNone(node_workbench)
        self.assertIn("display: grid;", node_panel.group("body"))
        self.assertIn("grid-template-rows: auto minmax(0, 1fr);", node_panel.group("body"))
        self.assertNotIn("height: 100%;", node_workbench.group("body"))

    def test_node_input_and_output_code_blocks_have_equal_height(self) -> None:
        styles = style_block(LANGGRAPH_HTML.read_text(encoding="utf-8"))
        node_code_blocks = re.search(
            r"\.node-io-grid \.log-block pre\s*\{(?P<body>[^}]*)\}",
            styles,
        )

        self.assertIsNotNone(node_code_blocks)
        body = node_code_blocks.group("body")
        self.assertIn("height: clamp(220px, 34dvh, 360px);", body)
        self.assertIn("max-height: none;", body)

    def test_history_reports_can_open_the_same_annotation_workbench(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            'id="history-tab"',
            'id="history-workspace"',
            'id="history-report-select"',
            'id="history-case-list"',
            'function loadHistoryReports()',
            'api("/api/history")',
            '`/api/history/${reportId}/cases/${index}`',
        ):
            self.assertIn(marker, langgraph)

    def test_node_regression_has_a_complete_frontend_workbench(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            'id="node-regression-tab"',
            'id="node-regression-workspace"',
            'id="node-regression-form"',
            'id="node-fixture-list"',
            'HTTP（应用节点接口）',
            'id="node-regression-base-url"',
            'id="node-regression-results"',
            'api("/api/node-regressions/fixtures")',
            'api("/api/node-regressions/jobs"',
            'function renderNodeRegressionJob(',
            'report.diffs',
        ):
            self.assertIn(marker, langgraph)

    def test_node_regression_only_offers_http_without_mock_toggle(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")
        form = re.search(
            r'<form id="node-regression-form".*?</form>', langgraph, re.DOTALL
        )

        self.assertIsNotNone(form)
        self.assertIn("HTTP（应用节点接口）", form.group())
        self.assertNotIn('id="node-regression-transport"', form.group())
        self.assertNotIn('id="node-regression-mock"', form.group())
        self.assertIn('transport: "http"', langgraph)
        self.assertIn("mock_external: false", langgraph)
        self.assertNotIn("syncNodeRegressionTransport", langgraph)

    def test_node_regression_disables_annotation_only_fixtures(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            "const replayableCases = Number(fixture.replayable_cases || 0);",
            "checkbox.disabled = replayableCases === 0;",
            "checkbox.checked = replayableCases > 0;",
            'row.classList.toggle("annotation-only", replayableCases === 0);',
            'count.textContent = replayableCases > 0',
            '`${replayableCases} 可回归 / ${annotationOnlyCases} 仅标注`',
            '`${fixture.cases || 0} 条 · 仅标注`',
        ):
            self.assertIn(marker, langgraph)

    def test_node_regression_results_use_queue_style_case_table_and_detail_dialog(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")

        for marker in (
            'id="node-regression-task-template"',
            'class="task-card node-regression-task-card"',
            'class="node-regression-case-list"',
            '<th>#</th><th>状态</th><th>用例 / 失败原因</th><th>耗时</th><th>详情</th>',
            'id="node-regression-detail-dialog"',
            'function renderNodeRegressionCases(',
            'function openNodeRegressionDetail(',
            'makeButton("查看", "node-regression-detail"',
            'data-node-regression-filter',
        ):
            self.assertIn(marker, langgraph)

    def test_node_regression_detail_wraps_long_paths_inside_the_field_column(self) -> None:
        styles = style_block(LANGGRAPH_HTML.read_text(encoding="utf-8"))

        path = re.search(
            r"\.node-regression-diff-table td:first-child code\s*\{(?P<body>[^}]*)\}",
            styles,
        )

        self.assertIsNotNone(path)
        self.assertIn("overflow-wrap: anywhere;", path.group("body"))
        self.assertIn("word-break: break-word;", path.group("body"))

    def test_node_regression_detail_uses_compact_diff_table(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")
        styles = style_block(langgraph)

        for marker in (
            'table.className = "node-regression-diff-table";',
            '["字段", "期望值", "实际值"]',
            'expected.className = "node-regression-value expected";',
            'actual.className = "node-regression-value actual";',
            '`${allDiffs.length} 个字段不一致`',
        ):
            self.assertIn(marker, langgraph)
        self.assertRegex(
            styles,
            r"#node-regression-detail-dialog\s*\{[^}]*width: min\(960px, calc\(100% - 32px\)\);",
        )

    def test_history_action_column_is_wide_enough_for_annotation_button(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")
        styles = style_block(langgraph)

        self.assertIn('<table class="history-table">', langgraph)
        self.assertRegex(
            styles,
            r"\.history-table th:nth-child\(5\),\s*"
            r"\.history-table td:nth-child\(5\)\s*\{[^}]*width: 112px;",
        )

    def test_desktop_config_panel_tracks_available_viewport_height(self) -> None:
        langgraph = LANGGRAPH_HTML.read_text(encoding="utf-8")
        styles = style_block(langgraph)

        self.assertRegex(
            styles,
            r"\.config-panel,\s*\.chat-config-panel\s*\{[^}]*"
            r"max-height: var\(--config-panel-max-height, calc\(100dvh - 194px\)\);"
            r"[^}]*overflow: auto;",
        )
        self.assertNotIn("max-height: calc(100dvh - 110px);", styles)
        for marker in (
            "function syncConfigPanelHeight()",
            "window.innerHeight - panelTop - bottomGap",
            'panel.style.setProperty("--config-panel-max-height"',
            'window.addEventListener("scroll", scheduleConfigPanelHeightSync, {passive: true});',
            'window.addEventListener("resize", scheduleConfigPanelHeightSync);',
            "scheduleConfigPanelHeightSync();",
        ):
            self.assertIn(marker, langgraph)


if __name__ == "__main__":
    unittest.main()
