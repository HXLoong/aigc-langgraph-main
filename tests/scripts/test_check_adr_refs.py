"""scripts/check_adr_refs.py 的单测。

覆盖三项复检能力：
1. ADR 互引虚悬检测（含相对 markdown 链接目标）
2. ADR 引用代码路径存在性——必须跳过 ``~~删除线~~`` 段
3. 引用热度 / 孤儿 ADR 统计（信息性输出，不算失败）
"""
from __future__ import annotations

from pathlib import Path

from scripts.check_adr_refs import (
    check_repo,
    find_dangling_adr_refs,
    find_missing_paths,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _mk_adr(tmp_path: Path, name: str, text: str) -> Path:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    p = adr_dir / name
    p.write_text(text, encoding="utf-8")
    return p


class TestDanglingAdrRefs:
    def test_dangling_number_detected(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "参见 ADR 0999 的决定。")
        findings = find_dangling_adr_refs(tmp_path / "docs" / "adr")
        assert any("0999" in f.detail for f in findings)

    def test_valid_ref_passes(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "参见 ADR 0002。")
        _mk_adr(tmp_path, "0002-b.md", "参见 ADR 0001。")
        assert find_dangling_adr_refs(tmp_path / "docs" / "adr") == []

    def test_adr_ref_without_space_detected(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "见 ADR0888。")
        findings = find_dangling_adr_refs(tmp_path / "docs" / "adr")
        assert any("0888" in f.detail for f in findings)

    def test_broken_relative_link_detected(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "[ADR 0002](./0002-not-there.md)")
        _mk_adr(tmp_path, "0002-b.md", "ok")
        findings = find_dangling_adr_refs(tmp_path / "docs" / "adr")
        assert any("0002-not-there.md" in f.detail for f in findings)

    def test_valid_relative_link_passes(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "[ADR 0002](./0002-b.md)")
        _mk_adr(tmp_path, "0002-b.md", "ok")
        assert find_dangling_adr_refs(tmp_path / "docs" / "adr") == []

    def test_broken_doc_link_detected(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "记录见 [归档](../archive/gone.md#sec)。")
        findings = find_dangling_adr_refs(tmp_path / "docs" / "adr")
        assert any("../archive/gone.md" in f.detail for f in findings)

    def test_valid_doc_link_and_urls_pass(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "guide.md").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "guide.md").write_text("ok", encoding="utf-8")
        _mk_adr(
            tmp_path,
            "0001-a.md",
            "[指南](../guide.md#x) · [官网](https://example.com/a.md) · [锚点](#d1)",
        )
        assert find_dangling_adr_refs(tmp_path / "docs" / "adr") == []

    def test_readme_links_checked(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "ok")
        _mk_adr(tmp_path, "README.md", "[0012](./0012-removed.md)")
        findings = find_dangling_adr_refs(tmp_path / "docs" / "adr")
        assert any(f.location == "README.md" for f in findings)


class TestMissingPaths:
    def test_missing_path_detected(self, tmp_path: Path) -> None:
        _mk_adr(tmp_path, "0001-a.md", "实现在 `app/nowhere/ghost.py` 中。")
        findings = find_missing_paths(tmp_path / "docs" / "adr", tmp_path)
        assert any("app/nowhere/ghost.py" in f.detail for f in findings)

    def test_existing_path_passes(self, tmp_path: Path) -> None:
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "real.py").write_text("x = 1\n", encoding="utf-8")
        _mk_adr(tmp_path, "0001-a.md", "实现在 `app/real.py` 中。")
        assert find_missing_paths(tmp_path / "docs" / "adr", tmp_path) == []

    def test_strikethrough_segment_skipped(self, tmp_path: Path) -> None:
        _mk_adr(
            tmp_path,
            "0001-a.md",
            "~~旧实现 `app/legacy/dead.py` 已废弃~~ 现在没有引用。",
        )
        assert find_missing_paths(tmp_path / "docs" / "adr", tmp_path) == []

    def test_line_number_suffix_stripped(self, tmp_path: Path) -> None:
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "real.py").write_text("x = 1\n", encoding="utf-8")
        _mk_adr(tmp_path, "0001-a.md", "见 `app/real.py:42` 与 `app/real.py:10-20`。")
        assert find_missing_paths(tmp_path / "docs" / "adr", tmp_path) == []

    def test_glob_and_placeholder_ignored(self, tmp_path: Path) -> None:
        _mk_adr(
            tmp_path,
            "0001-a.md",
            "如 `app/prompts/**/*.md` 与 `app/subgraphs/<product>/models.py`。",
        )
        assert find_missing_paths(tmp_path / "docs" / "adr", tmp_path) == []


class TestRealRepo:
    """对真实仓库跑全量检查——改写后的 21 篇 ADR 必须全部通过。"""

    def test_current_adrs_clean(self) -> None:
        result = check_repo(PROJECT_ROOT)
        problems = result.dangling + result.missing_paths
        assert problems == [], "\n".join(f.location + ": " + f.detail for f in problems)

    def test_heat_counts_nonempty(self) -> None:
        result = check_repo(PROJECT_ROOT)
        # 至少 0020（被 0010/0018 等多篇引用）计数 > 0
        assert result.heat.get("0020", 0) > 0
