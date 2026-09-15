"""#159 裁决落地：提示词治理两项。

1. judge 提示词从 langfuse_eval.py 硬编码抽到 app/prompts/judge/（ADR 0005 版本化要求）
2. export_dify_prompts.py 默认拒绝覆盖已存在文件（ADR 0003 的 Dify 同步保护）
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.prompts import clear_cache, load_prompt
from scripts.export_dify_prompts import extract_prompts_from_yaml, save_prompt_as_md

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIFY_WORKFLOW = PROJECT_ROOT / "dify" / "yaml" / "场外交易-test.yml"


@lru_cache(maxsize=1)
def _dify_prompt_templates() -> dict[str, dict[str, str]]:
    return {
        str(prompt["node_id"]): {
            message["role"]: message["text"].strip()
            for message in prompt["messages"]
        }
        for prompt in extract_prompts_from_yaml(DIFY_WORKFLOW)
    }


class TestDifyIsUpstreamNotTruth:
    """ADR 0022 D1（2026-09-15 拍板）：git .md 是唯一生产真源，Dify YAML 降为上游输入。

    2026-09-11 起曾按 node_id 把 7 个文件锁定为 YAML 逐字镜像；该锁定守的是文本相等而非
    代码契约（回归时删掉 confirm_order 枚举、代码未同步，见评估 SW-INC-01），且阻断了活跃
    27% 提示词的瘦身。现改为：manifest 登记 `dify: {file, node_id, system_sha256}`，
    `scripts/prompt_inventory.py` 在上游节点 sha 变化时**告警**（待人工 diff 合入），不阻断本地修改。
    """

    def test_every_mirrored_prompt_declares_upstream_mapping(self) -> None:
        from scripts import prompt_inventory as inv

        manifest = inv.load_manifest(inv.MANIFEST)
        templates = _dify_prompt_templates()
        for key, entry in manifest.items():
            entry = entry or {}
            if entry.get("status") != "active" or key.startswith("judge/"):
                continue
            dify = entry.get("dify")
            assert dify, f"{key} 为 active 但未登记 dify 映射（file/node_id/system_sha256）"
            if dify["file"] == DIFY_WORKFLOW.name:
                assert str(dify["node_id"]) in templates, f"{key} 映射的 node_id 不在 {DIFY_WORKFLOW.name}"

    def test_local_edit_does_not_break_governance(self) -> None:
        """锁定测试已退役：本地 .md 与 YAML 不相等只产生告警。"""
        from scripts import prompt_inventory as inv

        manifest = inv.load_manifest(inv.MANIFEST)
        warns = inv.check_upstream(PROJECT_ROOT / "dify" / "yaml", manifest)
        assert isinstance(warns, list)


class TestJudgePromptExtracted:
    def test_judge_prompt_loads_via_loader(self) -> None:
        clear_cache()
        p = load_prompt("judge", "option_judge")
        # 输出契约与宽松原则是 judge 语义核心，抽取时必须原样保留
        assert '"pass"' in p.system and '"score"' in p.system
        assert "宽松原则" in p.system
        assert "反案例" in p.system

    def test_eval_script_uses_loader_not_literal(self) -> None:
        """评估脚本必须走 load_prompt，不允许硬编码 judge 正文。"""
        text = (PROJECT_ROOT / "scripts" / "langfuse_eval.py").read_text(encoding="utf-8")
        assert 'load_prompt("judge", "option_judge")' in text
        assert "你是场外衍生品AI指令助手的测试审查员" not in text, (
            "langfuse_eval.py 仍硬编码 judge 提示词正文"
        )


class TestExportNoSilentOverwrite:
    _PROMPT = {
        "node_id": "n1",
        "title": "测试节点",
        "model": "m",
        "messages": [{"role": "system", "text": "sys"}],
    }

    def test_new_file_written(self, tmp_path: Path) -> None:
        assert save_prompt_as_md(self._PROMPT, tmp_path) is True
        assert (tmp_path / "测试节点.md").exists()

    def test_existing_file_not_overwritten_by_default(self, tmp_path: Path) -> None:
        target = tmp_path / "测试节点.md"
        target.write_text("旧版内容", encoding="utf-8")
        assert save_prompt_as_md(self._PROMPT, tmp_path) is False
        assert target.read_text(encoding="utf-8") == "旧版内容"

    def test_overwrite_flag_allows(self, tmp_path: Path) -> None:
        target = tmp_path / "测试节点.md"
        target.write_text("旧版内容", encoding="utf-8")
        assert save_prompt_as_md(self._PROMPT, tmp_path, overwrite=True) is True
        assert "sys" in target.read_text(encoding="utf-8")


class TestSyncScriptNoDefaultCredentials:
    """提示词治理评估 GOV-03：dify/sync.py 曾把内网 Dify 账号密码写成 argparse 默认值
    （CLAUDE.md「硬编码 API Key / Secret」P0 红线）。凭据只能来自环境变量或命令行。"""

    def test_no_literal_credentials(self) -> None:
        import re

        text = (PROJECT_ROOT / "dify" / "sync.py").read_text(encoding="utf-8")
        assert "wxzhoutao" not in text
        assert re.search(r'os\.environ\.get\("DIFY_(EMAIL|PASSWORD)",\s*"[^"]+"\)', text) is None
