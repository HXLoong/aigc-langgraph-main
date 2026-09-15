# 提示词管理规则

> 真源与状态机：[ADR 0022](../../docs/adr/0022-prompt-governance-after-code-migration.md)；
> 清单：`app/prompts/_manifest.yaml`（`python scripts/prompt_inventory.py` 打印，`--check` 进 CI）；
> 局部陷阱：`app/prompts/CLAUDE.md`。本文件只写"怎么做"，不复制清单与节点数（以 manifest 为准）。

## 三态与守护

| status | 含义 | lint 不变量 |
|---|---|---|
| `active` | 生产加载 | `loader` 文件里必须有 `load_prompt("<cat>", "<name>")` / `resolve_prompt_version(...)` 或 `loader_call` helper 调用 |
| `gray` | ADR 0003 灰度位（`*_v2.md`），由 `_versions.yaml` / `OTC_PROMPT_<CAT>_<NAME>_VERSION` 切流 | 记录 `base_system_sha256`；v1 之后被改 → 必须重做 diff 并写 `drift_acknowledged: {at_base_sha, note}`；`expires` 到期未转正 → 警告 |
| `inactive` | 无加载点的资产 | `reason` 必填（保留理由 + 可删条件）；`app/` 内零 `load_prompt` 引用 |

`--strict` 加严项（ADR 0022 D5 目标态，逐步收敛）：system 段里未在 `injects` 登记的 `{{#…#}}` 占位符视为**悬空**；走 `with_structured_output`（有 `output_model`）的文件里的 JSON 格式禁令视为死重。

## 占位符纪律（2026-09-15 反转）

Dify 的 `{{#node_id.var#}}` 在 Dify 由工作流引擎渲染；LangGraph 里**没有渲染层**。所以：

- 代码确实注入的占位符 → 在节点里 `system.replace(...)` 渲染（先例：`close/holding_query.py` 对手列表、`ticker/tools.py` 当前日期），并在 manifest `injects` 登记
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
- `injects` 必须与 manifest 该条目的 `injects` 一致（`tests/test_prompt_spec.py` 交叉核对）；`prompt_inventory.py --check` 把 `PromptSpec(category=, name=)` 视为加载点
- 灰度节点必须把 `build_messages` 返回的 `prompt_name` 写进 `TraceEntry.llm_output["prompt_name"]`（ADR 0003 硬前置，harness reporter 按此分桶）
- 尚未迁到 PromptSpec 的节点（close 5 个、swap select_* / multimodal、ticker、router）仍是 `load_prompt` / `resolve_prompt_version` 直调，按 ADR 0023 D5 分批迁移

## 来源优先级（ADR 0014 D3-2）

生产真源永远是 git 里的 `app/prompts/**/*.md`；`USE_LANGFUSE_PROMPTS=true` 只允许开发/staging 演练，生产开启即 fail-fast。LangFuse 演练稿用 `scripts/promote_langfuse_prompt.py` 晋升为 `_v{N+1}.md`（自动登记 manifest `gray`），再走 PR。

## 改提示词的三条路

| 场景 | 做法 | 门槛 |
|---|---|---|
| 瘦身 / 修规则（ADR 0022 D4 三档） | 零风险档直接改 v1；低风险档与需业务确认档走 `*_v2.md` 灰度位；都在 manifest `changelog` 加一行 | eval PASS ≥ v1 基线；`prompt(<scope>)` commit |
| Dify 侧有更新 | `python dify/sync.py`（凭据只从 `DIFY_EMAIL` / `DIFY_PASSWORD` 环境变量读）→ `scripts/export_dify_prompts.py`（默认不覆盖已存在文件）→ 人工 diff 选择性合入 | 不要一键覆盖；`prompt_inventory.py --check` 会按 manifest `dify.system_sha256` 告警哪些节点有上游更新，合入后更新该 sha |
| 新 LLM 节点 | `.md` 放对目录 + Pydantic Output 模型（每字段 `Field(description=)`）+ `PromptSpec` 声明 + `@safe_node` 节点 + manifest 登记（`output_model` / `injects`）+ golden case | `prompt_inventory.py --check` 通过 |

## 字符数 / 延迟

用 `python scripts/prompt_inventory.py` 看 system 字符与估算 tokens（÷1.6）；单请求开销按调用链累加（`docs/prompt-maintainability-assessment.md` 第二节）。当前最重路径：互换图片下单 ≈54K tokens、平仓下单 ≈37K、互换文本下单 ≈36K。

## Loader 缓存

`load_prompt()` 有 `@lru_cache`；测试里要重载用 `from app.prompts import clear_cache; clear_cache()`。

## 相关 ADR

- ADR 0001 D5：改写决定登记表（资产状态部分已由 manifest 接管）
- ADR 0003：同目录并存 + `_versions.yaml` 灰度（唯一版本化形态）
- ADR 0014：LangFuse 作为演练区，git 为真源
- ADR 0022：代码迁移完成后的提示词治理模型
- ADR 0023：提示词即代码（PromptSpec / AgentState inputs / Pydantic description 输出契约）
