"""prompt v1/v2 灰度切流测试（ADR 0003 同目录并存）。

覆盖：
- 默认（无 yaml 配置 / 无 env） → 返回 base_name（v1）
- env var override（`OTC_PROMPT_<CAT>_<NAME>_VERSION`）支持 v1 / v2 / 完整 name
- _versions.yaml weight 分流稳定性（同一 conversation_id 永远命中同一版本）
- conversation_id 缺失 → 固定取第一个版本
- yaml 解析失败 / 列表空 → 安全回退 base_name
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.prompts import (
    _hash_bucket,
    clear_cache,
    resolve_prompt_version,
)


@pytest.fixture(autouse=True)
def _isolate_cache() -> None:
    """每条测试前后清缓存，避免 yaml override 污染。"""
    clear_cache()
    yield
    clear_cache()


# ============================================================
# 1. 默认行为：无配置 → base_name
# ============================================================


def test_default_returns_base_name_when_no_config() -> None:
    """无 env / 无 yaml 配置时返回 base_name。"""
    assert resolve_prompt_version("swap", "intent", "conv-1") == "intent"
    assert resolve_prompt_version("option", "extract_inquiry", None) == "extract_inquiry"


# ============================================================
# 2. 环境变量 override
# ============================================================


def test_env_override_v1_returns_base_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "v1")
    assert resolve_prompt_version("swap", "intent", "conv-1") == "intent"


def test_env_override_v2_returns_versioned_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "v2")
    assert resolve_prompt_version("swap", "intent", "conv-1") == "intent_v2"


def test_env_override_v3_returns_versioned_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "v3")
    assert resolve_prompt_version("swap", "intent", None) == "intent_v3"


def test_env_override_full_name_returned_as_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 值不是 vN 格式时直接当 name 返回（开发者显式指定文件）。"""
    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "intent_experimental")
    assert resolve_prompt_version("swap", "intent", "conv-1") == "intent_experimental"


def test_env_override_handles_subcategory(monkeypatch: pytest.MonkeyPatch) -> None:
    """category 含 / 时正确转 env key。"""
    monkeypatch.setenv("OTC_PROMPT_OPTION_CLOSE_INTENT_VERSION", "v2")
    assert resolve_prompt_version("option_close", "intent", "x") == "intent_v2"


def test_env_override_empty_string_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "")
    assert resolve_prompt_version("swap", "intent", "conv-1") == "intent"


# ============================================================
# 3. yaml overrides + weight 分流
# ============================================================


def _write_versions_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "_versions.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_yaml_weight_split_routes_stably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一 conversation_id 永远命中同一版本（稳定性）。"""
    yaml_path = _write_versions_yaml(
        tmp_path,
        """
overrides:
  swap.intent:
    versions:
      - name: intent
        weight: 0.5
      - name: intent_v2
        weight: 0.5
""",
    )
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    clear_cache()

    cid = "stable-conv-001"
    first = resolve_prompt_version("swap", "intent", cid)
    for _ in range(50):
        assert resolve_prompt_version("swap", "intent", cid) == first


def test_yaml_weight_split_distributes_across_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对 1000 个不同 conversation_id 抽样，分流大致符合 weight 比例。"""
    yaml_path = _write_versions_yaml(
        tmp_path,
        """
overrides:
  swap.intent:
    versions:
      - name: intent
        weight: 0.7
      - name: intent_v2
        weight: 0.3
""",
    )
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    clear_cache()

    counts = {"intent": 0, "intent_v2": 0}
    for i in range(1000):
        name = resolve_prompt_version("swap", "intent", f"conv-{i}")
        counts[name] += 1

    # 70/30 期望，允许 ±5% 浮动
    assert 650 <= counts["intent"] <= 750, counts
    assert 250 <= counts["intent_v2"] <= 350, counts


def test_yaml_weight_full_traffic_to_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """weight=1.0 全量切 v2 → 所有 conversation_id 都命中 v2。"""
    yaml_path = _write_versions_yaml(
        tmp_path,
        """
overrides:
  swap.intent:
    versions:
      - name: intent_v2
        weight: 1.0
""",
    )
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    clear_cache()

    for i in range(20):
        assert resolve_prompt_version("swap", "intent", f"conv-{i}") == "intent_v2"


def test_yaml_no_conversation_id_picks_first_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """conversation_id 缺失时取列表第一个（视为默认 v1）。"""
    yaml_path = _write_versions_yaml(
        tmp_path,
        """
overrides:
  swap.intent:
    versions:
      - name: intent
        weight: 0.95
      - name: intent_v2
        weight: 0.05
""",
    )
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    clear_cache()

    assert resolve_prompt_version("swap", "intent", None) == "intent"
    assert resolve_prompt_version("swap", "intent", "") == "intent"


def test_env_override_takes_priority_over_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env var 优先级高于 yaml overrides。"""
    yaml_path = _write_versions_yaml(
        tmp_path,
        """
overrides:
  swap.intent:
    versions:
      - name: intent_v2
        weight: 1.0
""",
    )
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "v1")
    clear_cache()

    # env 强制 v1，即使 yaml 全量切了 v2
    assert resolve_prompt_version("swap", "intent", "x") == "intent"


# ============================================================
# 4. 异常 / 边界情形
# ============================================================


def test_yaml_missing_file_returns_base_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_versions.yaml 不存在时安全回退。"""
    monkeypatch.setattr(
        "app.prompts._VERSIONS_YAML", tmp_path / "nonexistent.yaml"
    )
    clear_cache()
    assert resolve_prompt_version("swap", "intent", "x") == "intent"


def test_yaml_malformed_returns_base_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_versions.yaml 语法错误时安全回退。"""
    yaml_path = _write_versions_yaml(tmp_path, "overrides: [malformed: [yaml:")
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    clear_cache()
    assert resolve_prompt_version("swap", "intent", "x") == "intent"


def test_yaml_empty_versions_list_returns_base_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yaml_path = _write_versions_yaml(
        tmp_path,
        """
overrides:
  swap.intent:
    versions: []
""",
    )
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    clear_cache()
    assert resolve_prompt_version("swap", "intent", "x") == "intent"


def test_yaml_irrelevant_key_returns_base_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配置了别的节点，当前节点不受影响。"""
    yaml_path = _write_versions_yaml(
        tmp_path,
        """
overrides:
  option.intent:
    versions:
      - name: intent_v2
        weight: 1.0
""",
    )
    monkeypatch.setattr("app.prompts._VERSIONS_YAML", yaml_path)
    clear_cache()

    assert resolve_prompt_version("swap", "intent", "x") == "intent"
    assert resolve_prompt_version("option", "intent", "x") == "intent_v2"


# ============================================================
# 5. _hash_bucket 工具函数
# ============================================================


def test_hash_bucket_is_stable() -> None:
    """同一 seed 永远 hash 到同一桶。"""
    assert _hash_bucket("conv-1") == _hash_bucket("conv-1")
    assert _hash_bucket("abc") == _hash_bucket("abc")


def test_hash_bucket_distributes_uniformly() -> None:
    """1000 个不同 seed 分布在不同桶（粗略验证 hash 没退化）。"""
    buckets = {_hash_bucket(f"conv-{i}") for i in range(1000)}
    # 至少 90% 唯一桶（10000 桶 / 1000 样本）
    assert len(buckets) >= 900
