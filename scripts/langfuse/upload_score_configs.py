"""全量同步人工标注使用的 Langfuse Score Configs 与 Annotation Queues。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.langfuse._definitions import load_definition_files, load_definition_list
from scripts.langfuse._public_api import LangfusePublicApi

DEFINITIONS_FILE = Path(__file__).with_name("definitions") / "score-configs.json"
ANNOTATION_QUEUES_FILE = Path(__file__).with_name("definitions") / "annotation-queues.json"
SCORE_DATA_TYPES = {"NUMERIC", "CATEGORICAL", "BOOLEAN", "TEXT"}


@dataclass(frozen=True)
class ScoreConfigDefinition:
    name: str
    description: str
    data_type: str
    categories: tuple[dict[str, Any], ...] = ()
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class ScoreConfigSyncResult:
    definition: ScoreConfigDefinition
    action: str


@dataclass(frozen=True)
class AnnotationQueueDefinition:
    name: str
    description: str
    score_configs: tuple[str, ...]


@dataclass(frozen=True)
class AnnotationQueueSyncResult:
    definition: AnnotationQueueDefinition
    action: str
    detail: str = ""


def _required_string(payload: dict[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Langfuse 定义缺少非空字符串 {key}：{path}")
    return value.strip()


def _optional_number(payload: dict[str, Any], key: str, path: Path) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise RuntimeError(f"Langfuse 定义字段 {key} 必须是数值：{path}")
    return float(value)


def load_score_config_definitions(
    definitions_path: Path = DEFINITIONS_FILE,
) -> tuple[ScoreConfigDefinition, ...]:
    definitions: list[ScoreConfigDefinition] = []
    raw_definitions = (
        load_definition_files(definitions_path)
        if definitions_path.is_dir()
        else load_definition_list(definitions_path, "score_configs")
    )
    for path, payload in raw_definitions:
        data_type = _required_string(payload, "data_type", path).upper()
        if data_type not in SCORE_DATA_TYPES:
            raise RuntimeError(f"不支持的 Score Config data_type：{data_type} ({path})")

        raw_categories = payload.get("categories", [])
        if not isinstance(raw_categories, list) or not all(
            isinstance(category, dict) for category in raw_categories
        ):
            raise RuntimeError(f"Score Config categories 必须是对象数组：{path}")
        categories = tuple(raw_categories)
        if data_type == "CATEGORICAL" and not categories:
            raise RuntimeError(f"CATEGORICAL Score Config 必须配置 categories：{path}")
        if data_type != "CATEGORICAL" and categories:
            raise RuntimeError(f"只有 CATEGORICAL Score Config 可配置 categories：{path}")

        definitions.append(
            ScoreConfigDefinition(
                name=_required_string(payload, "name", path),
                description=_required_string(payload, "description", path),
                data_type=data_type,
                categories=categories,
                min_value=_optional_number(payload, "min_value", path),
                max_value=_optional_number(payload, "max_value", path),
            )
        )

    names = [definition.name for definition in definitions]
    if len(names) != len(set(names)):
        raise RuntimeError("Score Config JSON 定义中存在重复名称")
    return tuple(definitions)


def load_annotation_queue_definitions(
    definitions_path: Path = ANNOTATION_QUEUES_FILE,
) -> tuple[AnnotationQueueDefinition, ...]:
    definitions: list[AnnotationQueueDefinition] = []
    for path, payload in load_definition_list(definitions_path, "annotation_queues"):
        raw_names = payload.get("score_configs")
        if not isinstance(raw_names, list) or not all(
            isinstance(name, str) and name.strip() for name in raw_names
        ):
            raise RuntimeError(f"Annotation Queue score_configs 必须是名称数组：{path}")
        score_configs = tuple(name.strip() for name in raw_names)
        if not score_configs:
            raise RuntimeError(f"Annotation Queue 至少要绑定一个 Score Config：{path}")
        if len(score_configs) != len(set(score_configs)):
            raise RuntimeError(f"Annotation Queue score_configs 存在重复名称：{path}")
        definitions.append(
            AnnotationQueueDefinition(
                name=_required_string(payload, "name", path),
                description=_required_string(payload, "description", path),
                score_configs=score_configs,
            )
        )

    names = [definition.name for definition in definitions]
    if len(names) != len(set(names)):
        raise RuntimeError("Annotation Queue JSON 定义中存在重复名称")
    return tuple(definitions)


class ScoreConfigApi(Protocol):
    def list_score_configs(self) -> list[dict[str, Any]]: ...

    def create_score_config(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_score_config(
        self, config_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


def _create_payload(definition: ScoreConfigDefinition) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": definition.name,
        "dataType": definition.data_type,
        "description": definition.description,
    }
    if definition.categories:
        payload["categories"] = list(definition.categories)
    if definition.min_value is not None:
        payload["minValue"] = definition.min_value
    if definition.max_value is not None:
        payload["maxValue"] = definition.max_value
    return payload


def _update_payload(definition: ScoreConfigDefinition) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": definition.name,
        "description": definition.description,
        "isArchived": False,
    }
    if definition.categories:
        payload["categories"] = list(definition.categories)
    if definition.min_value is not None:
        payload["minValue"] = definition.min_value
    if definition.max_value is not None:
        payload["maxValue"] = definition.max_value
    return payload


def sync_score_config(api: ScoreConfigApi, *, apply: bool) -> str:
    """兼容单 Score Config 调用；CLI 使用 sync_score_configs 全量同步。"""
    definition = load_score_config_definitions()[0]
    return sync_score_configs(
        api,
        definitions=(definition,),
        apply=apply,
    )[0].action


def sync_score_configs(
    api: ScoreConfigApi,
    *,
    definitions: tuple[ScoreConfigDefinition, ...] | None = None,
    apply: bool,
) -> list[ScoreConfigSyncResult]:
    if definitions is None:
        definitions = load_score_config_definitions()
    names = [definition.name for definition in definitions]
    if len(names) != len(set(names)):
        raise ValueError("Score Config 定义中存在重复名称")

    remote_configs = api.list_score_configs()
    results: list[ScoreConfigSyncResult] = []
    for definition in definitions:
        matched = [
            config
            for config in remote_configs
            if config.get("name") == definition.name
            and not config.get("isArchived")
        ]
        if len(matched) > 1:
            raise RuntimeError(f"远端存在多个有效 Score Config：{definition.name}")
        if not matched:
            if apply:
                api.create_score_config(_create_payload(definition))
                action = "created"
            else:
                action = "would_create"
            results.append(ScoreConfigSyncResult(definition, action))
            continue

        remote = matched[0]
        if remote.get("dataType") != definition.data_type:
            if not apply:
                results.append(ScoreConfigSyncResult(definition, "would_replace"))
                continue
            legacy_name = f"{definition.name}_old_{str(remote['id'])[:6]}"
            api.update_score_config(
                str(remote["id"]),
                {"name": legacy_name, "isArchived": True},
            )
            api.create_score_config(_create_payload(definition))
            results.append(ScoreConfigSyncResult(definition, "replaced"))
            continue

        desired = _update_payload(definition)
        if all(remote.get(key) == value for key, value in desired.items()):
            action = "unchanged"
        elif apply:
            api.update_score_config(str(remote["id"]), desired)
            action = "updated"
        else:
            action = "would_update"
        results.append(ScoreConfigSyncResult(definition, action))

    return results


class AnnotationQueueApi(Protocol):
    def list_annotation_queues(self) -> list[dict[str, Any]]: ...

    def create_annotation_queue(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def resolve_score_config_ids(api: ScoreConfigApi, *, apply: bool) -> dict[str, str]:
    """Score Config 名称 → 远端 id；dry-run 下尚未创建的用占位 id 占位。"""
    ids = {
        str(config["name"]): str(config["id"])
        for config in api.list_score_configs()
        if config.get("name") and config.get("id") and not config.get("isArchived")
    }
    if not apply:
        for definition in load_score_config_definitions():
            ids.setdefault(definition.name, f"<pending:{definition.name}>")
    return ids


def sync_annotation_queues(
    api: AnnotationQueueApi,
    *,
    score_config_ids: dict[str, str],
    definitions: tuple[AnnotationQueueDefinition, ...] | None = None,
    apply: bool,
) -> list[AnnotationQueueSyncResult]:
    if definitions is None:
        definitions = load_annotation_queue_definitions()

    remote_queues = api.list_annotation_queues()
    results: list[AnnotationQueueSyncResult] = []
    for definition in definitions:
        unknown = [name for name in definition.score_configs if name not in score_config_ids]
        if unknown:
            raise RuntimeError(
                f"Annotation Queue {definition.name} 引用了未定义的 Score Config："
                f"{', '.join(unknown)}"
            )
        desired_ids = [score_config_ids[name] for name in definition.score_configs]

        matched = [queue for queue in remote_queues if queue.get("name") == definition.name]
        if len(matched) > 1:
            raise RuntimeError(f"远端存在多个同名 Annotation Queue：{definition.name}")
        if not matched:
            if apply:
                api.create_annotation_queue(
                    {
                        "name": definition.name,
                        "description": definition.description,
                        "scoreConfigIds": desired_ids,
                    }
                )
                action = "created"
            else:
                action = "would_create"
            results.append(AnnotationQueueSyncResult(definition, action))
            continue

        remote_ids = [str(item) for item in matched[0].get("scoreConfigIds") or []]
        if sorted(remote_ids) == sorted(desired_ids):
            results.append(AnnotationQueueSyncResult(definition, "unchanged"))
            continue

        # Langfuse 只开放 queue 的 items / assignments 操作，没有 queue 级 update 或
        # delete，绑定不一致时只能人工在 UI 重建。
        results.append(
            AnnotationQueueSyncResult(
                definition,
                "drift",
                f"远端绑定 {remote_ids}，期望 {desired_ids}；需在 UI 重建该 queue",
            )
        )

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    api = LangfusePublicApi.from_env()
    results = sync_score_configs(api, apply=args.apply)
    print(f"Configured Score Configs: {len(results)}")
    for index, result in enumerate(results, start=1):
        print()
        print(f"[{index}/{len(results)}] Score Config:")
        print(f"  Name: {result.definition.name}")
        print(f"  Type: {result.definition.data_type}")
        print(f"  Categories: {len(result.definition.categories)}")
        print(f"  Action: {result.action}")

    queue_results = sync_annotation_queues(
        api,
        score_config_ids=resolve_score_config_ids(api, apply=args.apply),
        apply=args.apply,
    )
    print()
    print(f"Configured Annotation Queues: {len(queue_results)}")
    for index, result in enumerate(queue_results, start=1):
        print()
        print(f"[{index}/{len(queue_results)}] Annotation Queue:")
        print(f"  Name: {result.definition.name}")
        print(f"  Score Configs: {', '.join(result.definition.score_configs)}")
        print(f"  Action: {result.action}")
        if result.detail:
            print(f"  Detail: {result.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
