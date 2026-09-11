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
SYNCED_PROMPTS = (
    ("1755073106378", "option", "intent"),
    ("1779330004958", "option", "extract_inquiry"),
    ("17793301871440", "option", "extract_place"),
    ("1776159951508", "swap", "intent"),
    ("1776160580437", "swap", "place_order"),
    ("1780652808839", "swap", "select_counterparty"),
    ("1780652892832", "swap", "select_ticker"),
)


@lru_cache(maxsize=1)
def _dify_prompt_templates() -> dict[str, dict[str, str]]:
    return {
        str(prompt["node_id"]): {
            message["role"]: message["text"].strip()
            for message in prompt["messages"]
        }
        for prompt in extract_prompts_from_yaml(DIFY_WORKFLOW)
    }


def test_synced_prompts_match_dify_workflow() -> None:
    templates = _dify_prompt_templates()

    for node_id, category, name in SYNCED_PROMPTS:
        expected = templates[node_id]
        clear_cache()
        prompt = load_prompt(category, name)

        assert prompt.system == expected.get("system", ""), name
        assert prompt.user_template == expected.get("user", ""), name


class TestJudgePromptExtracted:
    def test_judge_prompt_loads_via_loader(self) -> None:
        clear_cache()
        p = load_prompt("judge", "option_judge")
        # 输出契约与宽松原则是 judge 语义核心，抽取时必须原样保留
        assert '"pass"' in p.system and '"score"' in p.system
        assert "宽松原则" in p.system
        assert "反案例" in p.system

    def test_eval_scripts_use_loader_not_literal(self) -> None:
        """两个评估脚本都必须走 load_prompt，不允许硬编码 judge 正文。"""
        for script in ("langfuse_eval.py", "langfuse_eval_clean.py"):
            text = (PROJECT_ROOT / "scripts" / script).read_text(encoding="utf-8")
            assert 'load_prompt("judge", "option_judge")' in text, script
            assert "你是场外衍生品AI指令助手的测试审查员" not in text, (
                f"{script} 仍硬编码 judge 提示词正文"
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
