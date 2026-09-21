"""提示词加载器。

从 `app/prompts/**/*.md` 加载提示词（git 是唯一真源，ADR 0024 D1）。
当 ENABLE_LANGFUSE=true 且 use_langfuse_prompts=true 时，优先从 Langfuse 拉取，
失败时回退到本地 .md 文件。

md 格式约定：
    # 提示词标题

    ## [system]
    ```
    <system 提示词内容；由代码渲染的 {{var}} 占位符须在 PromptSpec.injects 登记>
    ```

    ## [user]        ← 仅当 user 含规则文本时才有（先例 swap/place_order.md）
    ```
    <user 模板，{{var}} 经 render_user() 渲染>
    ```

使用方式：
    from app.prompts import load_prompt
    p = load_prompt("swap", "intent")
    # p.system → str
    # p.user_template → str（{{var}} 未渲染）
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
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent
_VERSIONS_YAML = PROMPTS_DIR / "_versions.yaml"
_HASH_BUCKETS = 10_000  # conversation_id hash 桶大小（4 位 16 进制 → 0..9999）


@dataclass(frozen=True)
class Prompt:
    """单条提示词，包含 system 与 user 两部分。"""
    name: str
    system: str
    user_template: str   # {{var}} 模板；无 [user] 段时为空串
    config: dict[str, Any] | None = None  # Langfuse 附带的 model / temperature 等

    def render_user(self, **kwargs: str) -> str:
        """把 user_template 中的 {{variable_name}} 占位符替换成实际值；未提供的占位符原样保留。"""
        text = self.user_template
        for k, v in kwargs.items():
            text = text.replace("{{" + k + "}}", str(v) if v is not None else "")
        return text


# 闭合围栏必须后跟下一节标题(## [...])或文件尾——否则 [system] 段内嵌套的
# ``` 围栏(如输出格式示例)会让非贪婪匹配提前截断(P1 迁移期发现的隐藏 bug,
# 曾把 option_close/cancel_close.md 从 4717 字符截到 1049)。
_MD_SYSTEM_RE = re.compile(
    r"##\s*\[system\]\s*\n+```[a-zA-Z]*\n(.*?)\n```(?=\s*(?:##\s*\[|\Z))",
    re.DOTALL,
)
_MD_USER_RE = re.compile(
    r"##\s*\[user\]\s*\n+```[a-zA-Z]*\n(.*?)\n```(?=\s*(?:##\s*\[|\Z))",
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


def _get_langfuse_client() -> Langfuse:
    """惰性构造 Langfuse 客户端（独立函数便于测试替换）。"""
    from langfuse import Langfuse

    return Langfuse()


def _load_from_langfuse(category: str, name: str) -> Prompt | None:
    """从 Langfuse 拉取提示词，失败返回 None。"""
    try:
        lf = _get_langfuse_client()
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
    except Exception as exc:  # noqa: BLE001
        # #155 裁决：从 debug 静默升为 warning——静默回退会掩盖
        # "以为在用 Langfuse 版实则本地版"的版本错配
        logger.warning("Langfuse 加载 %s/%s 失败，回退本地：%s", category, name, exc)
        logger.debug("Langfuse 加载失败详情", exc_info=True)
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
    if settings.use_langfuse_prompts and getattr(settings, "environment", "") == "production":
        # ADR 0014 D3-2 硬闸门（#155 裁决补齐）：生产提示词真理来源是 git .md，
        # 从 LangFuse 拉取会绕过 git PR 审计，误开即 fail-fast
        raise RuntimeError(
            "生产环境禁止从 LangFuse 拉取提示词（USE_LANGFUSE_PROMPTS 必须为 false，"
            "见 ADR 0014 D3-2 / issue #155）"
        )
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


# ============================================================
# v1/v2 灰度切流（ADR 0003 同目录并存模式）
# ============================================================


@lru_cache(maxsize=1)
def _load_versions_config() -> dict[str, dict[str, Any]]:
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
            return cast(str, v.get("name", base_name))

    last = versions[-1]
    return last.get("name", base_name) if isinstance(last, dict) else base_name


def clear_cache() -> None:
    """清空加载缓存（测试或热更新时使用）。"""
    load_prompt.cache_clear()
    _load_versions_config.cache_clear()
