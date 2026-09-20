"""全量同步人工标注使用的 Langfuse Score Configs。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.langfuse._definitions import load_definition_files
from scripts.langfuse._public_api import LangfusePublicApi

DEFINITIONS_DIR = Path(__file__).with_name("definitions") / "score-configs"
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
    directory: Path = DEFINITIONS_DIR,
) -> tuple[ScoreConfigDefinition, ...]:
    definitions: list[ScoreConfigDefinition] = []
    for path, payload in load_definition_files(directory):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    results = sync_score_configs(LangfusePublicApi.from_env(), apply=args.apply)
    print(f"Configured Score Configs: {len(results)}")
    for index, result in enumerate(results, start=1):
        print()
        print(f"[{index}/{len(results)}] Score Config:")
        print(f"  Name: {result.definition.name}")
        print(f"  Type: {result.definition.data_type}")
        print(f"  Categories: {len(result.definition.categories)}")
        print(f"  Action: {result.action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
