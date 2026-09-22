from __future__ import annotations

import json
from types import SimpleNamespace

from harness.evaluators.response_contains import evaluate as evaluate_contains
from harness.evaluators.response_contains_any import evaluate as evaluate_contains_any
from scripts.langfuse.upload_evaluators import load_evaluator_definitions
from scripts.langfuse.upload_score_configs import load_score_config_definitions


def _context(*, expected_output: dict, output: dict) -> SimpleNamespace:
    return SimpleNamespace(
        experiment=SimpleNamespace(item_expected_output=expected_output),
        observation=SimpleNamespace(output=output),
    )


def test_response_contains_requires_every_expected_line_per_turn() -> None:
    result = evaluate_contains(
        _context(
            expected_output={
                "response_contains": ["询价详情", "单号：Q-"],
                "sub_scenes": [{"response_contains": ["下单成功"]}],
            },
            output={
                "turns": [
                    {"reply_text": "询价详情\n单号：Q-20260921-001"},
                    {"reply_text": "参数不完整"},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.name == "det_required_text_pass"
    assert score.data_type == "BOOLEAN"
    assert score.value is False
    assert "第 2 轮缺少必含文本：下单成功" in (score.comment or "")


def test_response_contains_any_requires_one_candidate_per_turn() -> None:
    result = evaluate_contains_any(
        _context(
            expected_output={
                "response_contains_any": ["询价成功", "询价详情"],
                "sub_scenes": [
                    {"response_contains_any": ["下单成功", "委托成功"]}
                ],
            },
            output={
                "turns": [
                    {"reply_text": "场外期权询价详情"},
                    {"reply_text": "参数不完整"},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.name == "det_required_any_text_pass"
    assert score.data_type == "BOOLEAN"
    assert score.value is False
    assert "第 2 轮未命中任一候选文本" in (score.comment or "")
    assert "下单成功" in (score.comment or "")


def test_load_evaluators_from_one_definition_file(tmp_path) -> None:
    source_dir = tmp_path / "harness" / "evaluators"
    source_dir.mkdir(parents=True)
    evaluators = []
    for name in ("response-contains", "response-contains-any", "response-not-contains"):
        source = source_dir / f"{name.replace('-', '_')}.py"
        source.write_text("def evaluate(ctx):\n    return ctx\n", encoding="utf-8")
        evaluators.append(
            {
                "name": name,
                "description": name,
                "source": source.relative_to(tmp_path).as_posix(),
                "score_name": f"{name}-score",
                "rule": {"target": "experiment_item_root"},
            }
        )
    definition_file = tmp_path / "evaluators.json"
    definition_file.write_text(
        json.dumps({"evaluators": evaluators}), encoding="utf-8"
    )

    definitions = load_evaluator_definitions(
        definition_file,
        project_root=tmp_path,
    )

    assert [definition.name for definition in definitions] == [
        "response-contains",
        "response-contains-any",
        "response-not-contains",
    ]


def test_load_score_configs_from_one_definition_file(tmp_path) -> None:
    definition_file = tmp_path / "score-configs.json"
    definition_file.write_text(
        json.dumps(
            {
                "score_configs": [
                    {
                        "name": "human_business_verdict",
                        "description": "人工业务结论",
                        "data_type": "CATEGORICAL",
                        "categories": [
                            {"label": "正确", "value": 1},
                            {"label": "错误", "value": 0},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    definitions = load_score_config_definitions(definition_file)

    assert [definition.name for definition in definitions] == [
        "human_business_verdict"
    ]
