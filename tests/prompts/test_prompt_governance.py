"""批量评分不再发布或执行 Judge 提示词。"""
from pathlib import Path

from scripts.langfuse.langfuse_eval import judge_enabled


def test_no_judge_for_any_evaluation_suite():
    """旧 --no-judge 参数只作兼容，默认同样是确定性评分。"""
    assert not judge_enabled("intent")
    assert not judge_enabled("business")
    assert not (Path(__file__).resolve().parents[2] / "app/prompts/judge/option_judge.md").exists()
