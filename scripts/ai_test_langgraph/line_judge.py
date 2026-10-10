"""逐行断言的 LLM 裁判（回归工作台用，复用 app 标准 LLM / 提示词栈）。

- 模型：`app.llm.clients.get_qwen_standard()`（与业务节点同款 vendor 适配，ADR 0020）
- 输出契约：`LineAssertVerdict` + `with_structured_output`，不手工解析文本（项目核心原则 2）
- 提示词：`app/prompts/judge/assert_line.md`，经 `app.prompts.load_prompt` 加载（git 唯一真源）
- 启用策略：`.env` 配置 `QWEN_API_KEY` 时默认启用；`AI_TEST_LLM_JUDGE=0/false/off/no` 关闭
- 调用时机：仅对确定性断言已失败的行调用（`regression_support.evaluate_response` 的 judge 钩子）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from regression_support import JudgeCallable

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]

#: 显式关闭开关（测试工具专属，不进 app Settings）
_DISABLED_VALUES = {"0", "false", "off", "no"}


def _load_dotenv_into_environ(path: Path) -> None:
    """与 scripts/langfuse/langfuse_eval.py 同款 bootstrap：.env → os.environ。

    让 `get_settings()`（pydantic-settings 从环境变量读）在任意 cwd 下都能取到配置。
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.split("#")[0].strip()
        if key:
            os.environ[key] = value


_load_dotenv_into_environ(REPO_ROOT / ".env")

# app 包导入（build_line_judge 内惰性执行），仓库根需在 sys.path
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class LineAssertVerdict(BaseModel):
    """单行断言裁判输出契约。"""

    satisfied: bool = Field(
        description="实际回复是否语义上满足期望片段；单号/合约编号/额度/费率等动态值差异不影响满足性"
    )


def build_line_judge() -> JudgeCallable | None:
    """按 .env 构建逐行 LLM 断言裁判；不可用时返回 None（保持纯确定性断言）。"""
    if os.environ.get("AI_TEST_LLM_JUDGE", "").strip().lower() in _DISABLED_VALUES:
        return None
    try:
        from app.config import get_settings
        from app.llm.clients import get_qwen_standard
        from app.prompts import load_prompt
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception as exc:  # noqa: BLE001 - 无 app 依赖时降级为确定性断言
        print(f"[WARN] LLM 断言裁判不可用（依赖导入失败）：{exc}", file=sys.stderr)
        return None
    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 - 缺 .env / 配置不全时降级
        print(f"[WARN] LLM 断言裁判不可用（配置加载失败）：{exc}", file=sys.stderr)
        return None
    if not settings.qwen_api_key:
        return None
    system_prompt = load_prompt("judge", "assert_line").system
    structured = get_qwen_standard().with_structured_output(LineAssertVerdict)

    def judge(expected_line: str, answer: str) -> bool:
        verdict = structured.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"## 期望片段\n{expected_line}\n\n## 实际回复\n{answer}"),
            ]
        )
        return bool(verdict.satisfied)

    return judge
