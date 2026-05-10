"""提示词加载器。

从 `app/prompts/**/*.md` 中加载由 `scripts/export_dify_prompts.py` 导出的提示词。
当 ENABLE_LANGFUSE=true 且 use_langfuse_prompts=true 时，优先从 Langfuse 拉取，
失败时回退到本地 .md 文件。

md 格式约定：
    # 提示词标题
    - **node_id**: `...`
    - **model**: `...`

    ## [system]
    ```
    <system 提示词内容>
    ```

    ## [user]
    ```
    <user 模板，可能包含 {{#node.var#}} 变量占位符>
    ```

使用方式：
    from app.prompts import load_prompt
    p = load_prompt("swap", "intent")
    # p.system → str
    # p.user_template → str（原始 Dify 占位符未替换）
    # p.config → dict（Langfuse 附带的 model / temperature 等，本地加载时为 None）
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent
_VERSIONS_YAML = PROMPTS_DIR / "_versions.yaml"
_HASH_BUCKETS = 10_000  # conversation_id hash 桶大小（4 位 16 进制 → 0..9999）


@dataclass(frozen=True)
class Prompt:
    """单条提示词，包含 system 与 user 两部分。"""
    name: str
    system: str
    user_template: str   # 可能包含 Dify 占位符 {{#xxx.yyy#}}
    config: dict | None = None  # Langfuse 附带的 model / temperature 等

    def render_user(self, **kwargs: str) -> str:
        """把 user_template 中的 {{variable_name}} 占位符替换成实际值。

        注意：此方法只替换简单的 {{name}} 占位符。
        Dify 原始占位符（{{#node_id.var#}}）会被保留在原文中，
        视为大模型能够理解的上下文信息。
        """
        text = self.user_template
        for k, v in kwargs.items():
            text = text.replace("{{" + k + "}}", str(v) if v is not None else "")
        return text


_MD_SYSTEM_RE = re.compile(
    r"##\s*\[system\]\s*\n+```[a-zA-Z]*\n(.*?)\n```",
    re.DOTALL,
)
_MD_USER_RE = re.compile(
    r"##\s*\[user\]\s*\n+```[a-zA-Z]*\n(.*?)\n```",
    re.DOTALL,
)


def _parse_prompt_md(text: str) -> tuple[str, str]:
    """从 md 文本中提取 system 与 user 段。"""
    sys_match = _MD_SYSTEM_RE.search(text)
    user_match = _MD_USER_RE.search(text)
    system = sys_match.group(1).strip() if sys_match else ""
    user_template = user_match.group(1).strip() if user_match else ""
    return system, user_template


def _langfuse_name(category: str, name: str) -> str:
    """category/name → Langfuse prompt name（下划线连接）。"""
    return "_".join(category.split("/") + [name])


def _load_from_langfuse(category: str, name: str) -> Prompt | None:
    """从 Langfuse 拉取提示词，失败返回 None。"""
    try:
        from langfuse import Langfuse

        lf = Langfuse()
        lf_name = _langfuse_name(category, name)
        lf_prompt = lf.get_prompt(lf_name)

        if isinstance(lf_prompt.prompt, list):
            system = ""
            user_template = ""
            for msg in lf_prompt.prompt:
                if msg.get("role") == "system":
                    system = msg.get("content", "")
                elif msg.get("role") == "user":
                    user_template = msg.get("content", "")
        else:
            system = lf_prompt.prompt
            user_template = ""

        if not system:
            logger.warning("Langfuse 提示词 %s 无 system 内容，回退本地", lf_name)
            return None

        logger.info("从 Langfuse 加载: %s v%s", lf_name, lf_prompt.version)
        return Prompt(
            name=f"{category}/{name}",
            system=system,
            user_template=user_template,
            config=lf_prompt.config or {},
        )
    except Exception:
        logger.debug("Langfuse 加载 %s/%s 失败，回退本地", category, name, exc_info=True)
        return None


@lru_cache(maxsize=128)
def load_prompt(category: str, name: str) -> Prompt:
    """加载提示词，Langfuse 优先 + 本地 .md 兜底。

    当 enable_langfuse=true 且 use_langfuse_prompts=true 时，
    优先从 Langfuse 拉取，失败回退本地 .md。

    Args:
        category: 分类目录名，如 "swap" / "option_close" / "ticker"
        name: 文件名（不含 .md）

    Raises:
        FileNotFoundError: 对应文件不存在
    """
    from app.config import get_settings

    settings = get_settings()
    if settings.enable_langfuse and settings.use_langfuse_prompts:
        lf_prompt = _load_from_langfuse(category, name)
        if lf_prompt is not None:
            return lf_prompt

    # 本地 .md 兜底
    path = PROMPTS_DIR / category / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"提示词不存在：{path}。"
            f"可用的 category: {[p.name for p in PROMPTS_DIR.iterdir() if p.is_dir()]}"
        )

    text = path.read_text(encoding="utf-8")
    system, user_template = _parse_prompt_md(text)

    if not system:
        raise ValueError(f"{path} 未找到 [system] 段")

    return Prompt(name=f"{category}/{name}", system=system, user_template=user_template)


@lru_cache(maxsize=128)
def compose_prompt(category: str, name: str, version: str = "v1") -> Prompt:
    """版本化加载，支持把多个 md 片段拼装成一个 Prompt。

    - version="v1"：行为等同 load_prompt(category, name)，直接读原 md
    - version="v2"+：从 `{category}/{version}/` 子目录加载：
        1. `_base.md`（所有意图共享的规则基底）
        2. `{name}.md`（意图专属示例 / 输出约束）
      两者的 `[system]` 段按顺序拼接为最终 system prompt

    设计目的：
    - 把原本巨型单体 prompt 拆成 base + 意图片段，裁剪冗余示例降低延迟
    - 多个意图片段共享 base，避免规则被复制多份
    - 通过版本号做 A/B 切换，一键回滚 v1

    Args:
        category: 一级目录，如 "swap"
        name: 意图片段文件名（不含 .md），如 "place_order"
        version: "v1" 走原 load_prompt；"v2" 起走 {category}/{version}/ 子目录拼装

    Example:
        >>> p = compose_prompt("swap", "place_order", version="v2")
        >>> # p.system = swap/v2/_base.md 的 system + "\\n\\n" + swap/v2/place_order.md 的 system
    """
    if version == "v1":
        return load_prompt(category, name)

    subcat = f"{category}/{version}"
    base = load_prompt(subcat, "_base")
    leaf = load_prompt(subcat, name)

    merged_system = base.system + "\n\n" + leaf.system
    # user_template 优先取叶片段的；叶没定义就用 base 的（兜底）
    user_template = leaf.user_template or base.user_template
    return Prompt(
        name=f"{subcat}/{name}",
        system=merged_system,
        user_template=user_template,
    )


# ============================================================
# v1/v2 灰度切流（ADR 0003 同目录并存模式）
# ============================================================


@lru_cache(maxsize=1)
def _load_versions_config() -> dict[str, dict]:
    """读取并缓存 _versions.yaml 的 overrides 段。

    yaml 缺失或解析失败时返回空 dict（默认全部走 v1）。
    """
    if not _VERSIONS_YAML.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(_VERSIONS_YAML.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception("解析 %s 失败，回退默认 v1", _VERSIONS_YAML)
        return {}
    overrides = data.get("overrides")
    return overrides if isinstance(overrides, dict) else {}


_VERSION_TAG_RE = re.compile(r"^v\d+$")


def _resolve_env_override(category: str, base_name: str) -> str | None:
    """读取 `OTC_PROMPT_<CATEGORY>_<BASE_NAME>_VERSION` 覆盖。

    取值约定：
    - 空 / 未设 → None（不覆盖）
    - "v1" → base_name（生产默认）
    - "vN"（N ≥ 2）→ f"{base_name}_v{N}"（如 swap.intent + v2 → intent_v2）
    - 其他字符串 → 直接当 name 返回（开发者明确指定文件名时用）
    """
    env_key = (
        f"OTC_PROMPT_"
        f"{category.upper().replace('/', '_').replace('.', '_')}_"
        f"{base_name.upper()}_VERSION"
    )
    raw = os.environ.get(env_key)
    if not raw:
        return None
    value = raw.strip()
    if value == "v1":
        return base_name
    if _VERSION_TAG_RE.fullmatch(value):
        return f"{base_name}_{value}"
    return value


def _hash_bucket(seed: str) -> int:
    """conversation_id → 稳定 0.._HASH_BUCKETS-1 整数（sha256 前 8 位 16 进制）。"""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % _HASH_BUCKETS


def resolve_prompt_version(
    category: str,
    base_name: str,
    conversation_id: str | None = None,
) -> str:
    """按灰度配置返回应加载的 prompt name（不含 .md 后缀）。

    决策顺序（前者命中即短路）：
    1. 环境变量 `OTC_PROMPT_<CATEGORY>_<BASE_NAME>_VERSION` → 强制覆盖（开发调试）
    2. `_versions.yaml` `overrides[<category>.<base_name>]` 按 weight 分流
    3. 默认返回 base_name（v1，无后缀）

    分流稳定性：
    - 同一 conversation_id 永远命中同一版本（sha256 前 8 位 hex 取模）
    - conversation_id 为 None / 空 → 返回 versions 列表第一个（视为默认）

    Args:
        category: prompt 一级目录，如 "swap" / "option_close"
        base_name: 生产版文件名（不含后缀），如 "intent" / "place_order"
        conversation_id: 用于稳定 hash 分流；同一会话保持同一版本

    Returns:
        实际加载的 prompt name，如 "intent" 或 "intent_v2"

    Examples:
        >>> # 默认无配置 → v1
        >>> resolve_prompt_version("swap", "intent", "conv-1")
        'intent'

        >>> # _versions.yaml 配置了 95/5 灰度 + conversation_id 落到 v2 桶
        >>> # 同一 conversation_id 永远走同一版本
    """
    # 1. env var 强制覆盖
    env_name = _resolve_env_override(category, base_name)
    if env_name is not None:
        return env_name

    # 2. yaml overrides
    overrides = _load_versions_config()
    cfg = overrides.get(f"{category}.{base_name}")
    if not isinstance(cfg, dict):
        return base_name

    versions = cfg.get("versions")
    if not isinstance(versions, list) or not versions:
        return base_name

    # conversation_id 缺失：固定取第一个（默认）
    if not conversation_id:
        first = versions[0]
        return first.get("name", base_name) if isinstance(first, dict) else base_name

    total_weight = sum(
        float(v.get("weight", 1.0))
        for v in versions
        if isinstance(v, dict)
    )
    if total_weight <= 0:
        return base_name

    bucket_pos = _hash_bucket(conversation_id) / _HASH_BUCKETS  # 0.0 .. 1.0
    cumulative = 0.0
    for v in versions:
        if not isinstance(v, dict):
            continue
        cumulative += float(v.get("weight", 1.0)) / total_weight
        if bucket_pos < cumulative:
            return v.get("name", base_name)

    last = versions[-1]
    return last.get("name", base_name) if isinstance(last, dict) else base_name


def clear_cache() -> None:
    """清空加载缓存（测试或热更新时使用）。"""
    load_prompt.cache_clear()
    compose_prompt.cache_clear()
    _load_versions_config.cache_clear()
