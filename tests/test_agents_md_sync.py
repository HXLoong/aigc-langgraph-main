"""AGENTS.md（Codex / 其他 agent 读取）由 CLAUDE.md + .claude/rules/*.md 生成，禁止手改。

团队主用 Codex；Codex 只读 AGENTS.md（根 + 逐级子目录），不读 CLAUDE.md / .claude/rules。
为避免两套口径漂移，AGENTS.md 全部由 scripts/sync_agents_md.py 生成，CI --check 守同步。
"""
from __future__ import annotations

from pathlib import Path

from scripts import sync_agents_md as sync


def _mk(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text(
        "# 项目\n\n5. **TDD 强制**（/test-driven-development skill）—— 先写失败测试\n", encoding="utf-8"
    )
    (tmp_path / ".claude" / "rules" / "testing.md").write_text("# 测试规范\n\n- 规则甲\n", encoding="utf-8")
    (tmp_path / ".claude" / "rules" / "python-style.md").write_text("# 编码规范\n\n- 规则乙\n", encoding="utf-8")
    sub = tmp_path / "app" / "prompts"
    sub.mkdir(parents=True)
    (sub / "CLAUDE.md").write_text("# app/prompts · 局部约定\n\n> 规则见 `.claude/rules/prompt-management.md`\n", encoding="utf-8")
    return tmp_path


class TestRender:
    def test_root_contains_claude_md_and_all_rules(self, tmp_path):
        root = _mk(tmp_path)
        out = sync.render_root(root)
        assert "先写失败测试" in out
        assert "规则甲" in out and "规则乙" in out
        assert out.startswith("<!-- 自动生成")

    def test_claude_only_phrases_are_generalized(self, tmp_path):
        root = _mk(tmp_path)
        out = sync.render_root(root)
        assert "/test-driven-development skill" not in out
        assert ".claude/skills/test-driven-development/SKILL.md" in out

    def test_nested_agents_md_mirrors_local_claude_md(self, tmp_path):
        root = _mk(tmp_path)
        out = sync.render_nested(root / "app" / "prompts" / "CLAUDE.md")
        assert "局部约定" in out
        assert out.startswith("<!-- 自动生成")


class TestSyncAndCheck:
    def test_write_then_check_passes(self, tmp_path):
        root = _mk(tmp_path)
        written = sync.write_all(root)
        assert {p.relative_to(root).as_posix() for p in written} == {"AGENTS.md", "app/prompts/AGENTS.md"}
        assert sync.check_all(root) == []

    def test_check_detects_drift(self, tmp_path):
        root = _mk(tmp_path)
        sync.write_all(root)
        (root / "CLAUDE.md").write_text("# 项目\n\n改了\n", encoding="utf-8")
        errs = sync.check_all(root)
        assert any("AGENTS.md" in e and "过期" in e for e in errs)

    def test_check_detects_missing(self, tmp_path):
        root = _mk(tmp_path)
        errs = sync.check_all(root)
        assert any("不存在" in e for e in errs)


def test_real_repo_in_sync():
    assert sync.check_all(sync.PROJECT_ROOT) == []
