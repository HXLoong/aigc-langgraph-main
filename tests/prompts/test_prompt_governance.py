"""judge 提示词从 langfuse_eval.py 硬编码抽到 app/prompts/judge/（ADR 0005 版本化要求）。

（原第二项"export_dify_prompts.py 默认拒绝覆盖"随 Dify 同步链路退役删除，ADR 0024 D1。）
"""
from __future__ import annotations

from pathlib import Path

from app.prompts import clear_cache, load_prompt

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        text = (
            PROJECT_ROOT / "scripts" / "langfuse" / "langfuse_eval.py"
        ).read_text(encoding="utf-8")
        assert 'load_prompt("judge", "option_judge")' in text
        assert "你是场外衍生品AI指令助手的测试审查员" not in text, (
            "langfuse_eval.py 仍硬编码 judge 提示词正文"
        )
