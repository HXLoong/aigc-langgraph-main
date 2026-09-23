from __future__ import annotations

import json
import sys

from scripts.langfuse import upload_evaluators, upload_score_configs
from scripts.langfuse.upload_evaluators import (
    EvaluatorDefinition,
    load_evaluator_definitions,
    sync_evaluator,
    sync_evaluators,
)
from scripts.langfuse.upload_score_configs import (
    ScoreConfigDefinition,
    load_score_config_definitions,
    sync_score_config,
    sync_score_configs,
)


class FakeEvaluatorApi:
    def __init__(self) -> None:
        self.evaluators: list[dict] = []
        self.rules: list[dict] = []
        self.created_evaluator: dict | None = None
        self.created_rule: dict | None = None
        self.updated_evaluator: tuple[str, dict] | None = None
        self.updated_rule: tuple[str, dict] | None = None
        self.created_evaluators: list[dict] = []
        self.created_rules: list[dict] = []

    def get_dataset(self, name: str) -> dict:
        return {"id": "dataset-123", "name": name}

    def list_evaluators(self) -> list[dict]:
        return self.evaluators

    def create_evaluator(self, payload: dict) -> dict:
        self.created_evaluator = payload
        self.created_evaluators.append(payload)
        return {"id": f"evaluator-{payload['name']}", **payload, "version": 1}

    def update_evaluator(self, evaluator_id: str, payload: dict) -> dict:
        self.updated_evaluator = (evaluator_id, payload)
        return {"id": evaluator_id, **payload, "version": 2}

    def list_evaluation_rules(self) -> list[dict]:
        return self.rules

    def create_evaluation_rule(self, payload: dict) -> dict:
        self.created_rule = payload
        self.created_rules.append(payload)
        return {"id": f"rule-{len(self.created_rules)}", **payload}

    def update_evaluation_rule(self, rule_id: str, payload: dict) -> dict:
        self.updated_rule = (rule_id, payload)
        return {"id": rule_id, **payload}


class FakeScoreConfigApi:
    def __init__(self, configs: list[dict] | None = None) -> None:
        self.configs = configs or []
        self.created: dict | None = None
        self.updated: tuple[str, dict] | None = None
        self.created_configs: list[dict] = []

    def list_score_configs(self) -> list[dict]:
        return self.configs

    def create_score_config(self, payload: dict) -> dict:
        self.created = payload
        self.created_configs.append(payload)
        return {"id": f"score-config-{payload['name']}", **payload}

    def update_score_config(self, config_id: str, payload: dict) -> dict:
        self.updated = (config_id, payload)
        return {"id": config_id, **payload}


def test_load_evaluator_definitions_scans_one_json_per_evaluator(tmp_path) -> None:
    definitions_dir = tmp_path / "definitions"
    source_dir = tmp_path / "harness" / "evaluators"
    definitions_dir.mkdir()
    source_dir.mkdir(parents=True)
    (source_dir / "first.py").write_text("def evaluate(ctx):\n    return ctx\n")
    (source_dir / "second.py").write_text("def evaluate(ctx):\n    return ctx\n")
    (definitions_dir / "02-second.json").write_text(
        json.dumps(
            {
                "name": "second-check",
                "description": "second",
                "source": "harness/evaluators/second.py",
                "score_name": "second_score",
                "rule": {"target": "experiment_item_root"},
            }
        ),
        encoding="utf-8",
    )
    (definitions_dir / "01-first.json").write_text(
        json.dumps(
            {
                "name": "first-check",
                "description": "first",
                "source": "harness/evaluators/first.py",
                "score_name": "first_score",
                "rule": {"target": "experiment_item_root"},
            }
        ),
        encoding="utf-8",
    )

    definitions = load_evaluator_definitions(
        definitions_dir,
        project_root=tmp_path,
    )

    assert [definition.name for definition in definitions] == [
        "first-check",
        "second-check",
    ]
    assert definitions[0].source_path == source_dir / "first.py"


def test_load_score_config_definitions_scans_one_json_per_config(tmp_path) -> None:
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    (definitions_dir / "human-business-verdict.json").write_text(
        json.dumps(
            {
                "name": "human_business_verdict",
                "description": "人工结论；补充说明填写 Score Comment。",
                "data_type": "CATEGORICAL",
                "categories": [
                    {"label": "正确", "value": 1},
                    {"label": "错误", "value": 0},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    definitions = load_score_config_definitions(definitions_dir)

    assert [definition.name for definition in definitions] == [
        "human_business_verdict"
    ]
    assert definitions[0].data_type == "CATEGORICAL"
    assert definitions[0].categories == (
        {"label": "正确", "value": 1},
        {"label": "错误", "value": 0},
    )


def test_upload_evaluator_creates_dataset_scoped_rule(tmp_path) -> None:
    source = tmp_path / "response_not_contains.py"
    source.write_text("def evaluate(ctx):\n    return ctx\n", encoding="utf-8")
    api = FakeEvaluatorApi()

    result = sync_evaluator(
        api,
        dataset_name="golden_option_inquiry_case",
        source_path=source,
        apply=True,
    )

    assert result == {"evaluator": "created", "rule": "created"}
    assert api.created_evaluator == {
        "name": "response-not-contains",
        "description": "检查 Dataset 用例回复是否包含 response_not_contains 禁止文本。",
        "type": "code",
        "sourceCode": "def evaluate(ctx):\n    return ctx\n",
        "sourceCodeLanguage": "PYTHON",
    }
    assert api.created_rule is not None
    assert api.created_rule["evaluatorAssignments"] == [
        {"evaluatorId": "evaluator-response-not-contains", "variableMapping": None}
    ]
    assert api.created_rule["filter"] == [
        {
            "type": "boolean",
            "column": "isExperimentItemRootSpan",
            "operator": "=",
            "value": True,
        },
        {
            "type": "stringOptions",
            "column": "datasetId",
            "operator": "any of",
            "value": ["dataset-123"],
        },
    ]


def test_score_config_remote_difference_is_overwritten() -> None:
    api = FakeScoreConfigApi(
        [
            {
                "id": "score-config-1",
                "name": "human_business_verdict",
                "dataType": "CATEGORICAL",
                "categories": [{"label": "旧值", "value": 9}],
                "description": "旧说明",
                "isArchived": False,
            }
        ]
    )

    result = sync_score_config(api, apply=True)

    assert result == "updated"
    assert api.updated is not None
    config_id, payload = api.updated
    assert config_id == "score-config-1"
    assert payload["categories"] == [
        {"label": "正确", "value": 1},
        {"label": "错误", "value": 0},
        {"label": "待确认", "value": 0.5},
    ]
    assert "Score Comment" in payload["description"]


def test_upload_evaluator_repeated_run_skips_unchanged_remote(tmp_path) -> None:
    source = tmp_path / "response_not_contains.py"
    source_code = "def evaluate(ctx):\n    return ctx\n"
    source.write_text(source_code, encoding="utf-8")
    api = FakeEvaluatorApi()
    api.evaluators = [
        {
            "id": "evaluator-123",
            "name": "response-not-contains",
            "description": "检查 Dataset 用例回复是否包含 response_not_contains 禁止文本。",
            "type": "code",
            "sourceCode": source_code,
            "sourceCodeLanguage": "PYTHON",
        }
    ]
    api.rules = [
        {
            "id": "rule-123",
            "name": "golden-response-not-contains:golden_option_inquiry_case",
            "enabled": True,
            "sampling": 1.0,
            "filter": [
                {
                    "type": "boolean",
                    "column": "isExperimentItemRootSpan",
                    "operator": "=",
                    "value": True,
                },
                {
                    "type": "stringOptions",
                    "column": "datasetId",
                    "operator": "any of",
                    "value": ["dataset-123"],
                },
            ],
            "evaluatorAssignments": [
                {"evaluatorId": "evaluator-123", "variableMapping": None}
            ],
        }
    ]

    result = sync_evaluator(
        api,
        dataset_name="golden_option_inquiry_case",
        source_path=source,
        apply=True,
    )

    assert result == {"evaluator": "unchanged", "rule": "unchanged"}
    assert api.created_evaluator is None
    assert api.updated_evaluator is None
    assert api.created_rule is None
    assert api.updated_rule is None


def test_upload_evaluators_syncs_every_explicit_definition(tmp_path) -> None:
    first_source = tmp_path / "first.py"
    second_source = tmp_path / "second.py"
    first_source.write_text("def evaluate(ctx):\n    return ctx\n", encoding="utf-8")
    second_source.write_text("def evaluate(ctx):\n    return ctx\n", encoding="utf-8")
    definitions = (
        EvaluatorDefinition(
            name="first-check",
            description="first",
            source_path=first_source,
            score_name="first_score",
            target="experiment_item_root",
        ),
        EvaluatorDefinition(
            name="second-check",
            description="second",
            source_path=second_source,
            score_name="second_score",
            target="experiment_item_root",
        ),
    )
    api = FakeEvaluatorApi()

    results = sync_evaluators(
        api,
        dataset_name="golden_option_inquiry_case",
        definitions=definitions,
        apply=True,
    )

    assert [result.definition.name for result in results] == [
        "first-check",
        "second-check",
    ]
    assert [item["name"] for item in api.created_evaluators] == [
        "first-check",
        "second-check",
    ]
    assert [item["name"] for item in api.created_rules] == [
        "golden-first-check:golden_option_inquiry_case",
        "golden-second-check:golden_option_inquiry_case",
    ]


def test_upload_evaluator_without_dataset_creates_global_rule(tmp_path) -> None:
    source = tmp_path / "response_contains.py"
    source.write_text("def evaluate(ctx):\n    return ctx\n", encoding="utf-8")
    definition = EvaluatorDefinition(
        name="response-contains",
        description="required text",
        source_path=source,
        score_name="det_required_text_pass",
        target="experiment_item_root",
    )
    api = FakeEvaluatorApi()

    result = sync_evaluators(
        api,
        dataset_name=None,
        definitions=(definition,),
        apply=True,
    )[0]

    assert result.rule_name == "golden-response-contains:all-datasets"
    assert api.created_rule is not None
    assert api.created_rule["filter"] == [
        {
            "type": "boolean",
            "column": "isExperimentItemRootSpan",
            "operator": "=",
            "value": True,
        }
    ]


def test_upload_evaluator_cli_prints_readable_summary(monkeypatch, capsys) -> None:
    api = FakeEvaluatorApi()
    monkeypatch.setattr(
        upload_evaluators.LangfusePublicApi,
        "from_env",
        lambda: api,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "upload_evaluators.py",
            "--dataset-name",
            "golden_option_inquiry_case",
            "--dry-run",
        ],
    )

    assert upload_evaluators.main() == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == [
        "Target Dataset (Evaluation Rule filter): golden_option_inquiry_case",
        "Configured Evaluators: 3",
    ]
    for name in (
        "response-contains",
        "response-contains-any",
        "response-not-contains",
    ):
        assert f"  Name: {name}" in lines
        assert (
            f"    Name: golden-{name}:golden_option_inquiry_case" in lines
        )


def test_upload_score_config_cli_prints_readable_summary(monkeypatch, capsys) -> None:
    api = FakeScoreConfigApi()
    monkeypatch.setattr(
        upload_score_configs.LangfusePublicApi,
        "from_env",
        lambda: api,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["upload_score_configs.py", "--dry-run"],
    )

    assert upload_score_configs.main() == 0

    assert capsys.readouterr().out.splitlines() == [
        "Configured Score Configs: 1",
        "",
        "[1/1] Score Config:",
        "  Name: human_business_verdict",
        "  Type: CATEGORICAL",
        "  Categories: 3",
        "  Action: would_create",
    ]


def test_upload_score_configs_syncs_every_explicit_definition() -> None:
    definitions = (
        ScoreConfigDefinition(
            name="first_verdict",
            description="first",
            data_type="CATEGORICAL",
            categories=({"label": "通过", "value": 1},),
        ),
        ScoreConfigDefinition(
            name="second_verdict",
            description="second",
            data_type="CATEGORICAL",
            categories=({"label": "失败", "value": 0},),
        ),
    )
    api = FakeScoreConfigApi()

    results = sync_score_configs(api, definitions=definitions, apply=True)

    assert [result.definition.name for result in results] == [
        "first_verdict",
        "second_verdict",
    ]
    assert [item["name"] for item in api.created_configs] == [
        "first_verdict",
        "second_verdict",
    ]


def test_real_definitions_declare_suites() -> None:
    """业务集三个文本断言 + 意图集 intent_match，按 suite 分别绑定 Rule。"""
    definitions = load_evaluator_definitions()
    assert {definition.name: definition.suite for definition in definitions} == {
        "response-contains": "business",
        "response-contains-any": "business",
        "response-not-contains": "business",
        "intent-match": "intent",
        "instrument-match": "intent",
    }


def test_sync_evaluators_filters_by_suite(tmp_path) -> None:
    business_source = tmp_path / "business.py"
    intent_source = tmp_path / "intent.py"
    business_source.write_text("def evaluate(ctx):\n    return ctx\n", encoding="utf-8")
    intent_source.write_text("def evaluate(ctx):\n    return ctx\n", encoding="utf-8")
    definitions = (
        EvaluatorDefinition(
            name="business-check",
            description="business",
            source_path=business_source,
            score_name="business_score",
            target="experiment_item_root",
            suite="business",
        ),
        EvaluatorDefinition(
            name="intent-check",
            description="intent",
            source_path=intent_source,
            score_name="intent_score",
            target="experiment_item_root",
            suite="intent",
        ),
    )
    api = FakeEvaluatorApi()

    results = sync_evaluators(
        api,
        dataset_name="intent-swap",
        definitions=definitions,
        suite="intent",
        apply=True,
    )

    assert [result.definition.name for result in results] == ["intent-check"]
    assert [item["name"] for item in api.created_rules] == ["golden-intent-check:intent-swap"]


def test_resolve_evaluator_suite_from_dataset_name() -> None:
    assert upload_evaluators.resolve_evaluator_suite(None, "intent-swap") == "intent"
    assert upload_evaluators.resolve_evaluator_suite(None, "business-swap_prod_data") == "business"
    assert upload_evaluators.resolve_evaluator_suite(None, "golden_option_inquiry_case") == "business"
    assert upload_evaluators.resolve_evaluator_suite(None, None) == "business"
    assert upload_evaluators.resolve_evaluator_suite("intent", "golden_option_inquiry_case") == "intent"


def test_upload_evaluator_cli_binds_only_intent_evaluator_for_intent_dataset(
    monkeypatch, capsys
) -> None:
    api = FakeEvaluatorApi()
    monkeypatch.setattr(upload_evaluators.LangfusePublicApi, "from_env", lambda: api)
    monkeypatch.setattr(
        sys, "argv", ["upload_evaluators.py", "--dataset-name", "intent-swap", "--dry-run"]
    )

    assert upload_evaluators.main() == 0

    lines = capsys.readouterr().out.splitlines()
    assert "Configured Evaluators: 2" in lines
    assert "Suite: intent" in lines
    assert "  Name: intent-match" in lines
    assert "  Name: instrument-match" in lines
    assert "    Name: golden-intent-match:intent-swap" in lines
    assert "    Name: golden-instrument-match:intent-swap" in lines


def test_dataset_evaluator_metadata_excludes_instrument_scoring_without_labels(monkeypatch):
    api = FakeEvaluatorApi()
    monkeypatch.setattr(api, 'get_dataset', lambda name: {
        'id': 'option-dataset', 'name': name,
        'metadata': {'suite': 'intent', 'evaluator_names': ['intent-match']},
    })
    results = sync_evaluators(api, dataset_name='intent-option', suite='intent', apply=True)
    assert [r.definition.name for r in results] == ['intent-match']
    assert [r['name'] for r in api.created_rules] == ['golden-intent-match:intent-option']


def test_dataset_evaluator_metadata_cannot_cross_suite(monkeypatch):
    import pytest

    api = FakeEvaluatorApi()
    monkeypatch.setattr(api, 'get_dataset', lambda name: {
        'id': 'option-dataset', 'name': name,
        'metadata': {'suite': 'intent', 'evaluator_names': ['response-contains']},
    })
    with pytest.raises(ValueError, match='Evaluator'):
        sync_evaluators(api, dataset_name='intent-option', suite='intent', apply=True)
    assert not api.created_evaluators and not api.created_rules
