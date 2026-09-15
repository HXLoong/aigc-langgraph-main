"""提示词清单 + 治理 lint（scripts/prompt_inventory.py）。

ADR 0022：代码迁移完成后，`app/prompts/_manifest.yaml` 是"哪些 .md 活跃 / 灰度 / 非活跃"
的机器可读真源，替代 `app/prompts/CLAUDE.md` 手写清单。lint 守四条不变量：
  1. 目录 ↔ manifest 双向无孤儿
  2. active 条目的 loader 文件存在且真的引用了该 name
  3. inactive 条目在 app/ 内零 load_prompt 引用，且登记了保留理由
  4. gray 条目的 base（v1）自 v2 切出后未漂移（sha256 快照），漂移须显式 acknowledged
另有死重扫描（structured output 下的 JSON 格式禁令 / 未注入的 Dify 占位符）与字符预算。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import prompt_inventory as inv

_MD = "# t\n\n## [system]\n\n```\n{system}\n```\n\n## [user]\n\n```\n{user}\n```\n"


def _write_md(root: Path, key: str, system: str = "规则", user: str = "") -> Path:
    p = root / f"{key}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_MD.format(system=system, user=user), encoding="utf-8")
    return p


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def repo(tmp_path: Path) -> dict[str, Path]:
    prompts = tmp_path / "app" / "prompts"
    code = tmp_path / "app" / "subgraphs" / "demo"
    code.mkdir(parents=True)
    _write_md(prompts, "demo/intent", system="意图规则")
    (code / "intent.py").write_text(
        'from app.prompts import load_prompt\nprompt = load_prompt("demo", "intent")\n',
        encoding="utf-8",
    )
    return {"root": tmp_path, "prompts": prompts, "code": code}


# ============================================================
# 不变量 1 · 目录 ↔ manifest 双向无孤儿
# ============================================================


class TestOrphans:
    def test_md_without_manifest_entry_is_reported(self, repo):
        _write_md(repo["prompts"], "demo/stray")
        manifest = {"demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"}}
        errs = inv.check_orphans(repo["prompts"], manifest)
        assert any("demo/stray" in e and "未登记" in e for e in errs)

    def test_manifest_entry_without_md_is_reported(self, repo):
        manifest = {
            "demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"},
            "demo/ghost": {"status": "inactive", "reason": "x"},
        }
        errs = inv.check_orphans(repo["prompts"], manifest)
        assert any("demo/ghost" in e and "不存在" in e for e in errs)

    def test_consistent_manifest_passes(self, repo):
        manifest = {"demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"}}
        assert inv.check_orphans(repo["prompts"], manifest) == []


# ============================================================
# 不变量 2 / 3 · active 必须有真实加载点；inactive 必须零引用 + 有理由
# ============================================================


class TestLoaderReferences:
    def test_active_loader_must_reference_name(self, repo):
        (repo["code"] / "other.py").write_text("x = 1\n", encoding="utf-8")
        manifest = {"demo/intent": {"status": "active", "loader": "app/subgraphs/demo/other.py"}}
        errs = inv.check_loaders(repo["root"], manifest)
        assert any("demo/intent" in e and "未引用" in e for e in errs)

    def test_active_loader_missing_file(self, repo):
        manifest = {"demo/intent": {"status": "active", "loader": "app/nowhere.py"}}
        errs = inv.check_loaders(repo["root"], manifest)
        assert any("demo/intent" in e and "不存在" in e for e in errs)

    def test_active_ok(self, repo):
        manifest = {"demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"}}
        assert inv.check_loaders(repo["root"], manifest) == []

    def test_inactive_still_loaded_is_reported(self, repo):
        manifest = {"demo/intent": {"status": "inactive", "reason": "已去 LLM 化"}}
        errs = inv.check_loaders(repo["root"], manifest)
        assert any("demo/intent" in e and "仍被" in e for e in errs)

    def test_inactive_requires_reason(self, repo):
        _write_md(repo["prompts"], "demo/old")
        manifest = {"demo/old": {"status": "inactive"}}
        errs = inv.check_loaders(repo["root"], manifest)
        assert any("demo/old" in e and "reason" in e for e in errs)


# ============================================================
# 不变量 4 · gray（v2 灰度位）相对 base 的漂移
# ============================================================


class TestGrayDrift:
    def test_drift_detected_when_base_changed(self, repo):
        _write_md(repo["prompts"], "demo/intent_v2", system="瘦身规则")
        stale = _sha("切 v2 时的旧 v1 内容")
        manifest = {
            "demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"},
            "demo/intent_v2": {"status": "gray", "base": "demo/intent", "base_system_sha256": stale},
        }
        errs = inv.check_gray_drift(repo["prompts"], manifest)
        assert any("demo/intent_v2" in e and "漂移" in e for e in errs)

    def test_acknowledged_drift_is_warning_not_error(self, repo):
        _write_md(repo["prompts"], "demo/intent_v2", system="瘦身规则")
        manifest = {
            "demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"},
            "demo/intent_v2": {
                "status": "gray",
                "base": "demo/intent",
                "base_system_sha256": _sha("旧"),
                "drift_acknowledged": "2026-09-11 v1 被 Dify 回归更新，放量前须重做 diff",
            },
        }
        assert inv.check_gray_drift(repo["prompts"], manifest) == []

    def test_no_drift_passes(self, repo):
        _write_md(repo["prompts"], "demo/intent_v2", system="瘦身规则")
        manifest = {
            "demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"},
            "demo/intent_v2": {
                "status": "gray",
                "base": "demo/intent",
                "base_system_sha256": inv.system_sha256(repo["prompts"] / "demo" / "intent.md"),
            },
        }
        assert inv.check_gray_drift(repo["prompts"], manifest) == []

    def test_gray_requires_base_and_hash(self, repo):
        _write_md(repo["prompts"], "demo/intent_v2")
        manifest = {
            "demo/intent": {"status": "active", "loader": "app/subgraphs/demo/intent.py"},
            "demo/intent_v2": {"status": "gray"},
        }
        errs = inv.check_gray_drift(repo["prompts"], manifest)
        assert any("demo/intent_v2" in e and "base" in e for e in errs)


# ============================================================
# 死重扫描（报告项）
# ============================================================


class TestDeadWeightScan:
    def test_json_format_ban_detected(self, tmp_path):
        p = _write_md(
            tmp_path, "x/a",
            system="只输出纯 JSON，不要输出 markdown 代码块。\n禁止输出 ```json 标记。\n业务规则 A。",
        )
        r = inv.scan_dead_weight(p)
        assert r["json_format_ban_lines"] >= 2

    def test_dify_placeholders_counted(self, tmp_path):
        p = _write_md(tmp_path, "x/a", system="输入 {{#111.raw_content#}} 与 {{#222.list#}}")
        r = inv.scan_dead_weight(p)
        assert r["dify_placeholders"] == 2

    def test_unused_user_segment_flagged(self, tmp_path):
        p = _write_md(tmp_path, "x/a", system="s", user="query: {{#1.q#}}")
        r = inv.scan_dead_weight(p)
        assert r["user_chars"] > 0


# ============================================================
# 字符预算
# ============================================================


def test_budget_exceeded_reported(tmp_path):
    _write_md(tmp_path, "x/big", system="规" * 500)
    manifest = {"x/big": {"status": "active", "loader": "a.py", "max_system_chars": 100}}
    errs = inv.check_budget(tmp_path, manifest)
    assert any("x/big" in e and "超出" in e for e in errs)


# ============================================================
# 真实仓库：manifest 与目录/代码一致（CI 门）
# ============================================================


class TestRealRepo:
    def test_manifest_covers_repo(self):
        manifest = inv.load_manifest(inv.MANIFEST)
        assert manifest, "app/prompts/_manifest.yaml 为空"
        assert inv.check_orphans(inv.PROMPTS_DIR, manifest) == []
        assert inv.check_loaders(inv.PROJECT_ROOT, manifest) == []
        assert inv.check_gray_drift(inv.PROMPTS_DIR, manifest) == []
        assert inv.check_budget(inv.PROMPTS_DIR, manifest) == []

    def test_inventory_rows_cover_all_md(self):
        rows = inv.build_inventory(inv.PROMPTS_DIR, inv.load_manifest(inv.MANIFEST))
        md_files = [p for p in inv.PROMPTS_DIR.rglob("*.md") if p.name != "CLAUDE.md"]
        assert len(rows) == len(md_files)
        assert all(r["status"] in {"active", "gray", "inactive"} for r in rows)


# ============================================================
# ADR 0022 · 版本化形态收敛：compose_prompt / swap_prompt_version 死路径删除
# ============================================================


def test_compose_prompt_dead_path_removed():
    """#159 裁决遗留：compose_prompt + swap/v2/ 子目录拼装在 app/ 内零调用点，
    _versions.yaml 同目录并存是唯一版本化形态（ADR 0003），死路径不得复活。"""
    import app.prompts as prompts
    from app.config import Settings

    assert not hasattr(prompts, "compose_prompt")
    assert "swap_prompt_version" not in Settings.model_fields
