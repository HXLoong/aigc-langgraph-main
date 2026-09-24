"""scripts/check_docs_layout.py 的单测。

覆盖文档存放规则（docs/README.md「存放规则」）的五项检查：
1. docs/ 根目录只放白名单文件，子目录只用白名单主题
2. 每个主题目录有 README.md 索引
3. 文件名小写 kebab-case（README.md 例外）
4. 带日期的一次性报告只进 reports/，且按 YYYY-MM-DD-<topic>.md 命名
5. 链接有效：docs 内相对链接 + 全仓对 `docs/...` 路径的引用
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_docs_layout import (
    check_dated_names,
    check_file_names,
    check_readmes,
    check_relative_links,
    check_repo,
    check_repo_refs,
    check_root_layout,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str = "# t\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestRootLayout:
    def test_unknown_root_file_rejected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "README.md")
        _write(docs / "some-analysis.md")
        findings = check_root_layout(docs)
        assert any("some-analysis.md" in f.location for f in findings)

    def test_unknown_topic_dir_rejected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "README.md")
        _write(docs / "review" / "README.md")
        findings = check_root_layout(docs)
        assert any("review" in f.location for f in findings)

    def test_allowed_layout_passes(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "README.md")
        _write(docs / "work-plan.md")
        _write(docs / "operations" / "README.md")
        assert check_root_layout(docs) == []


class TestReadmes:
    def test_topic_dir_without_readme_rejected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "operations" / "on-call-runbook.md")
        findings = check_readmes(docs)
        assert any("operations" in f.location for f in findings)

    def test_topic_dir_with_readme_passes(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "operations" / "README.md")
        assert check_readmes(docs) == []


class TestFileNames:
    def test_upper_case_name_rejected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "deploy" / "SHADOW_COMPARE_GUIDE.md")
        findings = check_file_names(docs)
        assert any("SHADOW_COMPARE_GUIDE.md" in f.location for f in findings)

    def test_kebab_case_and_readme_pass(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "deploy" / "README.md")
        _write(docs / "deploy" / "shadow-compare-guide.md")
        _write(docs / "langfuse" / "images" / "00-evaluation-nav.png")
        _write(docs / "training" / "course" / "assets" / "course.css")
        assert check_file_names(docs) == []


class TestDatedNames:
    def test_dated_file_outside_reports_rejected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "testing" / "intent-dataset-assessment-2026-09-24.md")
        findings = check_dated_names(docs)
        assert any("intent-dataset-assessment" in f.location for f in findings)

    def test_report_without_date_prefix_rejected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "reports" / "option-review.md")
        findings = check_dated_names(docs)
        assert any("option-review.md" in f.location for f in findings)

    def test_dated_report_passes(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "reports" / "README.md")
        _write(docs / "reports" / "2026-09-24-option-review.md")
        assert check_dated_names(docs) == []

    def test_adr_numbers_are_not_dates(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "adr" / "0030-goal-restatement.md")
        assert check_dated_names(docs) == []


class TestRelativeLinks:
    def test_broken_markdown_link_detected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "README.md", "见 [架构](./ARCHITECTURE.md#分层)。")
        findings = check_relative_links(docs)
        assert any("ARCHITECTURE.md" in f.detail for f in findings)

    def test_broken_html_href_detected(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "training" / "a.html", '<a href="../missing.html">x</a>')
        findings = check_relative_links(docs)
        assert any("missing.html" in f.detail for f in findings)

    def test_valid_urls_and_anchors_pass(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        _write(docs / "architecture" / "README.md")
        _write(
            docs / "README.md",
            "[a](./architecture/README.md#x) [b](https://x.io/a.md) [c](#top) "
            "[d](mailto:a@b.c) [e](../CLAUDE.md)",
        )
        _write(tmp_path / "CLAUDE.md")
        assert check_relative_links(docs) == []


class TestRepoRefs:
    def test_missing_docs_path_in_script_detected(self, tmp_path: Path) -> None:
        _write(tmp_path / "docs" / "README.md")
        _write(tmp_path / "scripts" / "deploy.sh", "# 见 docs/deploy/langfuse-self-hosted.md\n")
        findings = check_repo_refs(tmp_path)
        assert any("docs/deploy/langfuse-self-hosted.md" in f.detail for f in findings)

    def test_existing_docs_path_and_external_url_pass(self, tmp_path: Path) -> None:
        _write(tmp_path / "docs" / "operations" / "on-call-runbook.md")
        _write(
            tmp_path / "app" / "main.py",
            '"""见 docs/operations/on-call-runbook.md 与 '
            'https://langfuse.com/docs/observability/overview.md"""\n',
        )
        assert check_repo_refs(tmp_path) == []

    def test_skips_git_and_venv(self, tmp_path: Path) -> None:
        _write(tmp_path / "docs" / "README.md")
        _write(tmp_path / ".venv" / "x.md", "docs/gone.md")
        _write(tmp_path / ".git" / "x.md", "docs/gone.md")
        assert check_repo_refs(tmp_path) == []


def test_real_repo_passes() -> None:
    result = check_repo(PROJECT_ROOT)
    assert result == [], "\n".join(f"{f.location}: {f.detail}" for f in result)
