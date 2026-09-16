# 提示词管理规则

> 真源与契约：[ADR 0023](../../docs/adr/0023-prompt-as-code-langgraph.md)（PromptSpec）；版本化 / 灰度：[ADR 0003](../../docs/adr/0003-prompt-versioning-by-file-coexistence.md)。
> 局部陷阱：`app/prompts/CLAUDE.md`。本文件只写"怎么做"。

## 占位符纪律（2026-09-15 反转）

Dify 的 `{{#node_id.var#}}` 在 Dify 由工作流引擎渲染；LangGraph 里**没有渲染层**。所以：

- 代码确实注入的占位符 → 在 `PromptSpec.injects` 登记渲染器（先例：`close/holding_query.py` 对手列表）；尚未迁到 PromptSpec 的节点用 `system.replace(...)` 渲染（先例：`ticker/tools.py` 当前日期）
- 代码不注入的占位符 → 是悬空规则，LLM 看到的是变量名；属零风险删除档，围绕它的整段规则一起删

## 加载方式（ADR 0023：一个 LLM 节点 = 一个 PromptSpec）

```python
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register

def _build_user_message(state: AgentState) -> str:      # 只拼变量，规则文本不进 Python
    return f"raw_content: {state.get('raw_text', '') or ''}\n\nhistory:\n{blocks.format_history(state.get('history_messages'))}"

SPEC = register(PromptSpec(
    category="swap", name="intent",
    output_model=SwapIntentOutput,                    # 输出契约唯一真源：每个字段写 Field(description=)
    inputs=("raw_text", "history_messages", "conversation_id"),   # 必须是 AgentState 字段，构造期校验
    user_builder=_build_user_message,
    injects={"{{#node.var#}}": lambda s: blocks.json_list(s.get("option_counterparties"))},  # system 占位符渲染
    gray=True,                                        # 走 _versions.yaml 灰度（resolve_prompt_version）
))

messages, prompt_name = SPEC.build_messages(state)    # [("system", ...), ("user", ...)]
result = await model.with_structured_output(SwapIntentOutput).ainvoke(messages)
```

- 节点默认只用 system 段 + 代码拼变量的 user；user 里若有**规则文本**，写进 `.md` 的 `[user]` 段用 `{{var}}` 占位，`user_builder` 里用 `load_prompt(...).render_user(**vars)` 渲染（先例 `swap/place_order.md`）
- **禁止**把提示词正文硬编码进 Python（含"后置追加一段格式指令"这种写法）；**禁止**在 `.md` 里维护 JSON 骨架 / 字段表——字段语义只写在 Pydantic `Field(description=)`
- 共享拼装（历史、对手列表、JSON 列表）只在 `app/prompts/blocks.py` 定义一次，不在子图里复制
- `injects` 登记的占位符必须在 `.md` system 段里真实存在，`build_messages` 构造期校验（`tests/test_prompt_spec.py`）
- 灰度节点必须把 `build_messages` 返回的 `prompt_name` 写进 `TraceEntry.llm_output["prompt_name"]`（ADR 0003 硬前置：进 `_versions.yaml` 前必须先写 trace，否则版本对比失真）
- 尚未迁到 PromptSpec 的节点（close 5 个、swap select_* / multimodal、ticker、router）仍是 `load_prompt` / `resolve_prompt_version` 直调，按 ADR 0023 D5 分批迁移

## 来源优先级（ADR 0014 D3-2）

生产真源永远是 git 里的 `app/prompts/**/*.md`；`USE_LANGFUSE_PROMPTS=true` 只允许开发/staging 演练，生产开启即 fail-fast。LangFuse 演练稿用 `scripts/promote_langfuse_prompt.py` 晋升为 `_v{N+1}.md`，再走 PR。

## 改提示词的三条路

| 场景 | 做法 | 门槛 |
|---|---|---|
| 瘦身 / 修规则 | 直接改 `app/prompts/**/*.md`；需要时先跑 `scripts/langfuse_eval.py` 对比 | 普通 PR review；`prompt(<scope>)` commit |
| Dify 侧有更新 | `python dify/sync.py`（凭据只从 `DIFY_EMAIL` / `DIFY_PASSWORD` 环境变量读）→ `scripts/export_dify_prompts.py`（默认不覆盖已存在文件）→ 人工 diff 选择性合入 | 不要一键覆盖 |
| 新 LLM 节点 | `.md` 放对目录 + Pydantic Output 模型（每字段 `Field(description=)`）+ `PromptSpec` 声明 + `@safe_node` 节点 + golden case | 普通 PR review |

## 字符数 / 延迟

单请求开销按调用链上各 `.md` system 字符 ÷1.6 估算 tokens 累加（基线盘点见 `docs/prompt-maintainability-assessment.md` 第二节）。当前最重路径：互换图片下单 ≈54K tokens、平仓下单 ≈37K、互换文本下单 ≈36K。

## Loader 缓存

`load_prompt()` 有 `@lru_cache`；测试里要重载用 `from app.prompts import clear_cache; clear_cache()`。

## 相关 ADR

- ADR 0001 D5：改写决定登记表
- ADR 0003：同目录并存 + `_versions.yaml` 灰度（唯一版本化形态）
- ADR 0014：LangFuse 作为演练区，git 为真源
- ADR 0022：代码迁移完成后的提示词治理模型（**已废弃**）
- ADR 0023：提示词即代码（PromptSpec / AgentState inputs / Pydantic description 输出契约）
