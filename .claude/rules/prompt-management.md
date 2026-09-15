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

## 加载方式

```python
from app.prompts import load_prompt, resolve_prompt_version

name = resolve_prompt_version("swap", "intent", conversation_id)   # 灰度位按 _versions.yaml 分流
p = load_prompt("swap", name)
llm = model.with_structured_output(SwapIntentOutput)
result = await llm.ainvoke([("system", p.system), ("user", user_message)])
```

- 节点只用 `p.system`；user 消息由节点代码拼装。`.md` 的 `[user]` 段只是 Dify 原始输入形态的参照
- **禁止**把提示词正文硬编码进 Python（含"后置追加一段格式指令"这种写法）
- 进 `_versions.yaml` 灰度的节点必须在 `TraceEntry.llm_output["prompt_name"]` 写实际加载的文件名（ADR 0003 硬前置，harness reporter 按此分桶）

## 来源优先级（ADR 0014 D3-2）

生产真源永远是 git 里的 `app/prompts/**/*.md`；`USE_LANGFUSE_PROMPTS=true` 只允许开发/staging 演练，生产开启即 fail-fast。LangFuse 演练稿用 `scripts/promote_langfuse_prompt.py` 晋升为 `_v{N+1}.md`（自动登记 manifest `gray`），再走 PR。

## 改提示词的三条路

| 场景 | 做法 | 门槛 |
|---|---|---|
| 瘦身 / 修规则（ADR 0022 D4 三档） | 零风险档直接改 v1；低风险档与需业务确认档走 `*_v2.md` 灰度位；都在 manifest `changelog` 加一行 | eval PASS ≥ v1 基线；`prompt(<scope>)` commit |
| Dify 侧有更新 | `python dify/sync.py`（凭据只从 `DIFY_EMAIL` / `DIFY_PASSWORD` 环境变量读）→ `scripts/export_dify_prompts.py`（默认不覆盖已存在文件）→ 人工 diff 选择性合入 | 不要一键覆盖；`prompt_inventory.py --check` 会按 manifest `dify.system_sha256` 告警哪些节点有上游更新，合入后更新该 sha |
| 新 LLM 节点 | `.md` 放对目录 + Pydantic Output 模型 + `@safe_node` 节点 + manifest 登记 + golden case | `prompt_inventory.py --check` 通过 |

## 字符数 / 延迟

用 `python scripts/prompt_inventory.py` 看 system 字符与估算 tokens（÷1.6）；单请求开销按调用链累加（`docs/prompt-maintainability-assessment.md` 第二节）。当前最重路径：互换图片下单 ≈54K tokens、平仓下单 ≈37K、互换文本下单 ≈36K。

## Loader 缓存

`load_prompt()` 有 `@lru_cache`；测试里要重载用 `from app.prompts import clear_cache; clear_cache()`。

## 相关 ADR

- ADR 0001 D5：改写决定登记表（资产状态部分已由 manifest 接管）
- ADR 0003：同目录并存 + `_versions.yaml` 灰度（唯一版本化形态）
- ADR 0014：LangFuse 作为演练区，git 为真源
- ADR 0022：代码迁移完成后的提示词治理模型
