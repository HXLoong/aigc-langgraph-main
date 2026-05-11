# Dify 提示词管理规则

## 当前阶段：**重构期内可改写**（ADR 0001 D5）

`app/prompts/**/*.md` 来源于 Dify 生产工作流 YAML（由 `python dify/sync.py` 拉取 + `scripts/export_dify_prompts.py` 导出）。

**纪律切换**：
- 重构完成前（shadow PASS 之前）：**允许定向改写**，但每一处改写必须在 ADR 0001 D5 的"处置表"中登记。
- 重构完成后：恢复"只读资产"纪律——只做加载，不改内容。

已登记的允许改写范围（其他不许扩散）：
- **合并**：swap 三个"确认 X"节点 → 1 个 `swap.confirm(expected_action)` 统一 confirm 提示词
- **拆分**：option 单一 2870 行 intent_extract → 1 个 intent + 5 个 extract（`extract_inquiry` / `extract_place_or_modify` / `extract_cancel` / `extract_confirm` / `extract_query`）
- **保持**：其他 15 个 LLM 节点 1:1 复刻，提示词照搬

## 提示词目录结构（M1 完成后）

```
app/prompts/
├── swap/            # 互换
├── option/          # 期权（询价/下单/改单/撤单）
├── option_close/    # 期权平仓
└── ticker/          # 标的识别
```

具体文件清单以 M2 实际产出为准（节点数：swap 10 + option 6 + option_close 7 + ticker 1 = 24）。

## 加载方式

```python
from app.prompts import load_prompt

p = load_prompt("swap", "intent")
# p.system → str
# p.user_template → str（保留 Dify 原始 {{#node.var#}} 占位符）
# p.config → dict | None（LangFuse 来源会带 model/temperature；本地 .md 加载为 None）

llm = qwen.with_structured_output(SwapIntentOutput)
result = await llm.ainvoke([
    ("system", p.system),
    ("user", user_message),
])
```

**禁止**：把提示词内容硬编码进 Python 源码。

## 提示词来源优先级（ADR 0014）

```
ENABLE_LANGFUSE=true 且 use_langfuse_prompts=true
    → 优先从 LangFuse 拉（运行时可热更）
    → 失败回退到本地 app/prompts/**/*.md

否则
    → 直接读本地 .md
```

## 在重构期内调整提示词

### 场景 A：直接改写（已登记的两种）

合并 / 拆分写新提示词时：

1. 直接在 `app/prompts/<category>/<name>.md` 创建/覆盖文件
2. 用 `python -m harness run --category <prefix>` 跑相关 golden 子集
3. 提交时 commit message 用 `prompt(<scope>): ...` 类型，引用 ADR 0001 D5

### 场景 B：保持 1:1 复刻，但要尝试改进

走 A/B 共存路线（ADR 0003）：

1. 创建新版本 `app/prompts/<category>/<name>_v2.md`（保留 v1）
2. 在节点函数里临时切换 `load_prompt("...", "<name>_v2")`
3. 跑 `python -m harness run` 对比两版差异
4. 显著优于 v1（且业务认可）才合并 v2 → v1，并删 v2

### 场景 C：从 Dify 同步最新版

```bash
# 1. 拉 Dify 最新 YAML
export DIFY_EMAIL="..." DIFY_PASSWORD="..."
python dify/sync.py                                       # → dify/yaml/

# 2. 导出到临时目录
python scripts/export_dify_prompts.py dify/yaml/ /tmp/new-prompts/

# 3. 对比差异，**不要一键覆盖**
diff -r app/prompts/ /tmp/new-prompts/ | head -50

# 4. 选择性合入
# 5. 跑 harness 回归
python -m harness run
```

## 为新 LLM 节点接入提示词

1. 把 .md 放到 `app/prompts/<category>/` 正确位置
2. 在 `app/subgraphs/<product>/...` 定义对应 Pydantic Output 模型（M2 子图重建期路径以 ADR 0006 的产出为准）
3. 节点函数：`@safe_node` + `load_prompt()` + `llm.with_structured_output(...)`
4. golden 加 5-10 条 case（`tests/fixtures/*.jsonl`）
5. `python -m harness run --category <prefix>` 验证

## 字符数 / 延迟提示

- swap/place_order.md ≈ 133K 字符 ≈ 40K tokens（Qwen3-30B 上下文上限的一半）
- 长提示词显著影响 P95 延迟
- 评估时记录延迟，过高考虑拆分（option 已是先例）

## 占位符处理

Dify 的 `{{#node_id.var#}}` 占位符（如 `{{#1775913928411.date#}}`）**保留原样**——LLM 能理解为上下文标记。
不要用 regex 替换它们，会破坏 Dify 行为对齐。

## Loader 缓存

`load_prompt()` 内部 `@lru_cache(maxsize=128)`，启动后重复加载零成本。
测试中需要重新加载：`from app.prompts import clear_cache; clear_cache()`

## 相关 ADR

- ADR 0001 D5：节点合并/拆分策略 + 重构期内纪律调整
- ADR 0003：提示词版本化通过文件共存（v1 / v2 并存）
- ADR 0011：option intent 拆分二次修订
- ADR 0013：动态推理片段加载
- ADR 0014：LangFuse 作为 harness 后端 + 提示词运行时来源
