"""全量同步 Langfuse Code Evaluators 及其 Online Evaluation Rules。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS_FILE = Path(__file__).with_name("definitions") / "evaluators.json"

sys.path.insert(0, str(PROJECT_ROOT))

from scripts.langfuse._definitions import load_definition_files, load_definition_list
from scripts.langfuse._public_api import LangfusePublicApi


@dataclass(frozen=True)
class EvaluatorDefinition:
    name: str
    description: str
    source_path: Path
    score_name: str
    target: str


@dataclass(frozen=True)
class EvaluatorSyncResult:
    definition: EvaluatorDefinition
    evaluator_action: str
    rule_name: str
    rule_action: str


def _required_string(payload: dict[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Langfuse 定义缺少非空字符串 {key}：{path}")
    return value.strip()


def load_evaluator_definitions(
    definitions_path: Path = DEFINITIONS_FILE,
    *,
    project_root: Path = PROJECT_ROOT,
) -> tuple[EvaluatorDefinition, ...]:
    root = project_root.resolve()
    definitions: list[EvaluatorDefinition] = []
    raw_definitions = (
        load_definition_files(definitions_path)
        if definitions_path.is_dir()
        else load_definition_list(definitions_path, "evaluators")
    )
    for path, payload in raw_definitions:
        source_value = _required_string(payload, "source", path)
        source_path = (root / source_value).resolve()
        try:
            source_path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"Evaluator 源码必须位于项目目录内：{path}") from exc
        if not source_path.is_file():
            raise RuntimeError(f"Evaluator 源码不存在：{source_path}")

        rule = payload.get("rule")
        if not isinstance(rule, dict):
            raise RuntimeError(f"Evaluator 定义缺少 rule 对象：{path}")
        target = _required_string(rule, "target", path)
        if target != "experiment_item_root":
            raise RuntimeError(f"不支持的 Evaluator Rule target：{target} ({path})")

        definitions.append(
            EvaluatorDefinition(
                name=_required_string(payload, "name", path),
                description=_required_string(payload, "description", path),
                source_path=source_path,
                score_name=_required_string(payload, "score_name", path),
                target=target,
            )
        )

    names = [definition.name for definition in definitions]
    if len(names) != len(set(names)):
        raise RuntimeError("Evaluator JSON 定义中存在重复名称")
    return tuple(definitions)


class EvaluatorApi(Protocol):
    def get_dataset(self, name: str) -> dict[str, Any]: ...

    def list_evaluators(self) -> list[dict[str, Any]]: ...

    def create_evaluator(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_evaluator(
        self, evaluator_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    def list_evaluation_rules(self) -> list[dict[str, Any]]: ...

    def create_evaluation_rule(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_evaluation_rule(
        self, rule_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


def _one_named(items: list[dict[str, Any]], name: str, kind: str) -> dict[str, Any] | None:
    matched = [item for item in items if item.get("name") == name]
    if len(matched) > 1:
        raise RuntimeError(f"远端存在多个同名 {kind}：{name}，无法确定稳定 ID")
    return matched[0] if matched else None


def _evaluator_payload(
    definition: EvaluatorDefinition, source: str
) -> dict[str, Any]:
    return {
        "name": definition.name,
        "description": definition.description,
        "type": "code",
        "sourceCode": source,
        "sourceCodeLanguage": "PYTHON",
    }


def _rule_payload(
    *,
    definition: EvaluatorDefinition,
    dataset_name: str | None,
    dataset_id: str | None,
    evaluator_id: str,
) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [
        {
            "type": "boolean",
            "column": "isExperimentItemRootSpan",
            "operator": "=",
            "value": True,
        }
    ]
    if dataset_id is not None:
        filters.append(
            {
                "type": "stringOptions",
                "column": "datasetId",
                "operator": "any of",
                "value": [dataset_id],
            }
        )
    scope = dataset_name or "all-datasets"
    return {
        "name": f"golden-{definition.name}:{scope}",
        "enabled": True,
        "sampling": 1.0,
        "filter": filters,
        "evaluatorAssignments": [
            {"evaluatorId": evaluator_id, "variableMapping": None}
        ],
    }


def _same_fields(remote: dict[str, Any], desired: dict[str, Any]) -> bool:
    return all(remote.get(key) == value for key, value in desired.items())


def sync_evaluator(
    api: EvaluatorApi,
    *,
    dataset_name: str,
    source_path: Path | None = None,
    apply: bool,
) -> dict[str, str]:
    """兼容单 Evaluator 调用；CLI 使用 sync_evaluators 全量同步。"""
    definition = next(
        item
        for item in load_evaluator_definitions()
        if item.name == "response-not-contains"
    )
    if source_path is not None:
        definition = replace(definition, source_path=source_path)
    result = sync_evaluators(
        api,
        dataset_name=dataset_name,
        definitions=(definition,),
        apply=apply,
    )[0]
    return {
        "evaluator": result.evaluator_action,
        "rule": result.rule_action,
    }


def sync_evaluators(
    api: EvaluatorApi,
    *,
    dataset_name: str | None,
    definitions: tuple[EvaluatorDefinition, ...] | None = None,
    apply: bool,
) -> list[EvaluatorSyncResult]:
    if definitions is None:
        definitions = load_evaluator_definitions()
    names = [definition.name for definition in definitions]
    if len(names) != len(set(names)):
        raise ValueError("Evaluator 定义中存在重复名称")

    dataset_id: str | None = None
    if dataset_name:
        dataset = api.get_dataset(dataset_name)
        dataset_id = str(dataset.get("id") or "")
        if not dataset_id:
            raise RuntimeError(f"Dataset 缺少 id：{dataset_name}")

    remote_evaluators = api.list_evaluators()
    remote_rules = api.list_evaluation_rules()
    results: list[EvaluatorSyncResult] = []

    for definition in definitions:
        source = definition.source_path.read_text(encoding="utf-8")
        desired_evaluator = _evaluator_payload(definition, source)
        remote_evaluator = _one_named(
            remote_evaluators, definition.name, "Evaluator"
        )

        if remote_evaluator is None:
            evaluator_action = "created" if apply else "would_create"
            if not apply:
                results.append(
                    EvaluatorSyncResult(
                        definition=definition,
                        evaluator_action=evaluator_action,
                        rule_name=(
                            f"golden-{definition.name}:"
                            f"{dataset_name or 'all-datasets'}"
                        ),
                        rule_action="would_create",
                    )
                )
                continue
            remote_evaluator = api.create_evaluator(desired_evaluator)
        elif _same_fields(remote_evaluator, desired_evaluator):
            evaluator_action = "unchanged"
        else:
            evaluator_action = "updated" if apply else "would_update"
            if apply:
                remote_evaluator = api.update_evaluator(
                    str(remote_evaluator["id"]), desired_evaluator
                )

        evaluator_id = str(remote_evaluator.get("id") or "")
        if not evaluator_id:
            raise RuntimeError(f"Evaluator 缺少稳定 id：{definition.name}")

        desired_rule = _rule_payload(
            definition=definition,
            dataset_name=dataset_name,
            dataset_id=dataset_id,
            evaluator_id=evaluator_id,
        )
        remote_rule = _one_named(
            remote_rules, desired_rule["name"], "Evaluation Rule"
        )
        if remote_rule is None:
            rule_action = "created" if apply else "would_create"
            if apply:
                api.create_evaluation_rule(desired_rule)
        elif _same_fields(remote_rule, desired_rule):
            rule_action = "unchanged"
        else:
            rule_action = "updated" if apply else "would_update"
            if apply:
                api.update_evaluation_rule(str(remote_rule["id"]), desired_rule)

        results.append(
            EvaluatorSyncResult(
                definition=definition,
                evaluator_action=evaluator_action,
                rule_name=str(desired_rule["name"]),
                rule_action=rule_action,
            )
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-name")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    results = sync_evaluators(
        LangfusePublicApi.from_env(),
        dataset_name=args.dataset_name,
        apply=args.apply,
    )
    target = args.dataset_name or "all datasets"
    print(f"Target Dataset (Evaluation Rule filter): {target}")
    print(f"Configured Evaluators: {len(results)}")
    for index, result in enumerate(results, start=1):
        print()
        print(
            f"[{index}/{len(results)}] Project-level Evaluator "
            "(not bound to a Dataset):"
        )
        print(f"  Name: {result.definition.name}")
        source = result.definition.source_path.relative_to(PROJECT_ROOT).as_posix()
        print(f"  Source: {source}")
        print(f"  Score: {result.definition.score_name}")
        print(f"  Action: {result.evaluator_action}")
        print()
        print("  Evaluation Rule (trigger conditions):")
        print(f"    Name: {result.rule_name}")
        print(f"    Evaluates: Experiment Item root output in {target}")
        print(f"    Action: {result.rule_action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
