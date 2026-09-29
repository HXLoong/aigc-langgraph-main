from __future__ import annotations

import json

from scripts.langfuse.upload_evaluators import load_evaluator_definitions
from scripts.langfuse.upload_score_configs import load_score_config_definitions


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
