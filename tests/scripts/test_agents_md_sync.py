"""AGENTS.md 与 .agents/skills/（Codex 读取）由 CLAUDE.md / .claude/ 生成，禁止手改。

团队主用 Codex；Codex 只读 AGENTS.md（根 + 逐级子目录）与 .agents/skills/<name>/SKILL.md，
不读 CLAUDE.md / .claude/rules / .claude/skills。为避免两套口径漂移，全部由
scripts/sync_agents_md.py 生成，提交前 --check 守同步。
"""
from __future__ import annotations

from pathlib import Path

from scripts import sync_agents_md as sync


def _mk(tmp_path: Path) -> Path:
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text(
        "# 项目\n\n5. **TDD 强制**（/test-driven-development skill）—— 先写失败测试\n", encoding="utf-8"
    )
    (rules / "testing.md").write_text("# 测试规范\n\n- 规则甲\n", encoding="utf-8")
    (rules / "prompt-management.md").write_text("# 提示词管理规则\n\n- 规则丙\n", encoding="utf-8")
    (rules / "python-style.md").write_text("# Python 编码规范\n\n- 规则乙\n", encoding="utf-8")
    (rules / "docs.md").write_text("# 文档存放规则\n\n- 规则丁\n", encoding="utf-8")
    (rules / "langgraph-patterns.md").write_text("# LangGraph 模式\n\n- 规则戊\n", encoding="utf-8")
    sub = tmp_path / "app" / "prompts"
    sub.mkdir(parents=True)
    (sub / "CLAUDE.md").write_text("# app/prompts · 局部约定\n\n> 规则见 `.claude/rules/prompt-management.md`\n", encoding="utf-8")
    sk = tmp_path / ".claude" / "skills" / "add-intent"
    (sk / "references").mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "---\nname: add-intent\ndescription: 新增意图\nargument-hint: <product> <intent>\nallowed-tools: Read, Bash\n---\n\n"
        "# 新增\n\n- `$1` = 产品\n", encoding="utf-8"
    )
    (sk / "references" / "notes.md").write_text("参考\n", encoding="utf-8")
    ag = tmp_path / ".claude" / "agents"
    ag.mkdir()
    (ag / "test-generator.md").write_text(
        "---\nname: test-generator\ndescription: 生成测试\ntools: Read, Write\nmodel: sonnet\n---\n\n你是测试专家。\n", encoding="utf-8"
    )
    return tmp_path


class TestRenderRoot:
    def test_merges_only_listed_rules(self, tmp_path):
        out = sync.render_root(_mk(tmp_path))
        assert "规则甲" in out and "规则丙" in out
        assert "规则乙" not in out
        assert ".claude/rules/python-style.md" in out  # 其余规则以链接列出

    def test_merges_docs_rule_so_codex_sees_doc_placement(self, tmp_path):
        out = sync.render_root(_mk(tmp_path))
        assert "规则丁" in out

    def test_merges_langgraph_patterns_so_codex_sees_graph_rules(self, tmp_path):
        out = sync.render_root(_mk(tmp_path))
        assert "规则戊" in out

    def test_claude_only_phrases_are_generalized(self, tmp_path):
        out = sync.render_root(_mk(tmp_path))
        assert "/test-driven-development skill" not in out
        assert ".claude/skills/test-driven-development/SKILL.md" in out
        assert out.startswith("<!-- 自动生成")

    def test_nested_agents_md_mirrors_local_claude_md(self, tmp_path):
        root = _mk(tmp_path)
        out = sync.render_nested(root / "app" / "prompts" / "CLAUDE.md")
        assert "局部约定" in out and out.startswith("<!-- 自动生成")


class TestRenderSkills:
    def test_skill_frontmatter_keeps_only_standard_fields(self, tmp_path):
        root = _mk(tmp_path)
        out = sync.render_skill(root / ".claude" / "skills" / "add-intent" / "SKILL.md")
        fm = out.split("---")[1]
        assert "name: add-intent" in fm and "description: 新增意图" in fm
        assert "allowed-tools" not in fm and "argument-hint" not in fm
        assert "argument_hint" in fm  # 放进 metadata
        assert "`$1` = 产品" in out
        assert "自动生成" in out and "$1" in out

    def test_agent_definition_becomes_skill(self, tmp_path):
        root = _mk(tmp_path)
        out = sync.render_agent_as_skill(root / ".claude" / "agents" / "test-generator.md")
        fm = out.split("---")[1]
        assert "name: test-generator" in fm and "description: 生成测试" in fm
        assert "model:" not in fm and "tools:" not in fm
        assert "你是测试专家" in out

    def test_targets_include_skills_and_references(self, tmp_path):
        root = _mk(tmp_path)
        rel = {p.relative_to(root).as_posix() for p in sync.targets(root)}
        assert ".agents/skills/add-intent/SKILL.md" in rel
        assert ".agents/skills/add-intent/references/notes.md" in rel
        assert ".agents/skills/test-generator/SKILL.md" in rel


class TestSyncAndCheck:
    def test_write_then_check_passes(self, tmp_path):
        root = _mk(tmp_path)
        sync.write_all(root)
        assert sync.check_all(root) == []

    def test_check_detects_drift(self, tmp_path):
        root = _mk(tmp_path)
        sync.write_all(root)
        (root / "CLAUDE.md").write_text("# 项目\n\n改了\n", encoding="utf-8")
        errs = sync.check_all(root)
        assert any("AGENTS.md" in e and "过期" in e for e in errs)

    def test_check_detects_missing(self, tmp_path):
        errs = sync.check_all(_mk(tmp_path))
        assert any("不存在" in e for e in errs)


def test_real_repo_in_sync():
    assert sync.check_all(sync.PROJECT_ROOT) == []
