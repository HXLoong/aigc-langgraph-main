# Prompt v1/v2 灰度切流操作手册

> 落地：ADR 0003「同目录文件并存」+ ADR 0001 D5「Dify 重构期内可改写」
> 适用范围：`app/prompts/<category>/<name>.md`（如 `swap/intent.md`）的 A/B 实验

## 何时用？

1. **修复结构性 LLM 误判**（如 g008 swap.intent 偶发误判）
2. **裁剪冗余示例降低延迟**（结合 ADR 0003 子目录 `compose_prompt` 模式）
3. **验证 Dify 新版同步前的 prompt 改动**（先小流量灰度，再全量切换）

## 文件命名约定

| 文件 | 含义 |
|---|---|
| `app/prompts/swap/intent.md` | 当前生产版本（v1，无后缀）|
| `app/prompts/swap/intent_v2.md` | A/B 候选版本 |
| `app/prompts/swap/intent_v3.md` | 后续候选 |

**写新版规则**：
- 新版**保留 Dify 原文结构**（system / user 段、占位符 `{{#node.var#}}`），只改业务逻辑相关段落
- 同一节点最多并存 2 个版本（v1 + 新版），稳定 7 天后清理老版本

## 触发灰度的 3 种方式

### 方式 A：环境变量强制覆盖（开发调试 / 紧急回滚）

```bash
# 全量切到 v2
export OTC_PROMPT_SWAP_INTENT_VERSION=v2

# 紧急回滚到 v1
export OTC_PROMPT_SWAP_INTENT_VERSION=v1

# 指定任意文件名（绕过 vN 约定）
export OTC_PROMPT_SWAP_INTENT_VERSION=intent_experimental
```

环境变量名规则：`OTC_PROMPT_<CATEGORY>_<BASE_NAME>_VERSION`
- category 中 `/` 与 `.` 都转为 `_`，整体转大写
- 例：`option_close.intent` → `OTC_PROMPT_OPTION_CLOSE_INTENT_VERSION`

### 方式 B：`_versions.yaml` 灰度（生产推荐）

编辑 `app/prompts/_versions.yaml`：

```yaml
overrides:
  swap.intent:
    versions:
      - name: intent       # → app/prompts/swap/intent.md（v1）
        weight: 0.95
      - name: intent_v2    # → app/prompts/swap/intent_v2.md
        weight: 0.05
```

- weight 必须为正数；不要求和为 1.0（内部会归一化）
- **同一 conversation_id 永远命中同一版本**（sha256 前 8 位 hex 取模 10000 桶）
- 改 yaml 后无需重启（`clear_cache()` 或下次进程启动生效）

### 方式 C：什么都不配（默认）

`overrides: {}` 时所有节点走 v1（base_name），与历史行为一致。

## 优先级

1. **环境变量**（最高）— 用于开发调试 / 紧急回滚
2. **`_versions.yaml`** — 生产灰度
3. **默认 v1** — 无配置时

## 节点接入示例

`app/subgraphs/swap/intent.py`（已接入）：

```python
from app.prompts import load_prompt, resolve_prompt_version

@safe_node
async def swap_intent(state: AgentState) -> dict[str, Any]:
    conversation_id = state.get("conversation_id")
    prompt_name = resolve_prompt_version("swap", "intent", conversation_id)
    prompt = load_prompt("swap", prompt_name)
    # ... 调 LLM ...
    return {
        "intent": result.type,
        "trace": [
            TraceEntry(
                node="swap_intent",
                decision=f"intent={result.type} prompt={prompt_name}",
                llm_output={"type": result.type, "prompt_name": prompt_name},
            )
        ],
    }
```

**关键**：trace.llm_output 必须记录 `prompt_name`，否则 A/B 评估失去对比依据。

## 评估流程

1. 配置灰度（方式 B）— 5% 流量切 v2
2. 运行 24 小时 → 收集两版 case 的 LangFuse trace
3. 按 prompt_name 分组对比 PASS 率
4. v2 PASS 率 ≥ v1 才扩大流量；否则回滚（删 yaml 配置）
5. v2 全量稳定 7 天 → 删 v1 文件，把 v2 改回无后缀

## 测试

```bash
pytest tests/test_prompt_versioning.py -v
```

18 条用例覆盖：环境变量 / yaml 分流 / 稳定性 / 异常回退。

## 常见 FAQ

**Q：灰度期间日志怎么追？**
A：trace `llm_output.prompt_name` 字段，按 `prompt_name=intent_v2` 过滤。

**Q：同一 conversation_id 多次进入会不会被路由到不同版本？**
A：不会。sha256 hash 决定桶位，weights 决定阈值，二者都稳定 → 同一会话稳定路由。

**Q：weight 总和不等于 1.0 怎么办？**
A：内部会按 `weight / total_weight` 归一化。建议保持总和为 1.0 便于阅读。

**Q：env var 和 yaml 同时配置，哪个生效？**
A：env var 优先（`test_env_override_takes_priority_over_yaml` 已覆盖）。

**Q：版本号能跳号吗？**
A：可以。env var 设 `v5` → 加载 `intent_v5.md`。但建议顺序递增便于追溯。

## 参考

- ADR 0003 — 提示词版本化采用"同目录文件并存"
- ADR 0001 D5 — Dify 重构期内可改写
- `app/prompts/__init__.py` — `resolve_prompt_version` / `_load_versions_config` / `_hash_bucket` 实现
