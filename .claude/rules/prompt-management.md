# Dify 提示词管理规则

## 核心原则：Dify 提示词是**只读资产**

`app/prompts/**/*.md` 下的 23 个提示词是从 Dify 生产工作流 YAML 原封导出的，
它们是生产验证过的业务逻辑资产。**不要修改内容**，只改加载和使用方式。

## 提示词目录结构

```
app/prompts/
├── swap/            # 互换（8 个）
│   ├── intent.md                    （20K 字符）
│   ├── place_order.md               （133K 字符，最大的一个）
│   ├── confirm_order.md / cancel_order.md / confirm_cancel.md
│   ├── confirm_modify.md / query_order.md
│   ├── image_extract.md / image_ocr.md
│   └── excel_extract.md
├── option_close/    # 期权平仓（7 个）
│   ├── intent.md / place_close.md / holding_query.md
│   └── confirm_close.md / cancel_close.md / confirm_cancel.md / query_status.md
└── ticker/          # 标的识别（4 个）
    ├── tokenize.md / completeness.md / rank.md / infer_code.md
```

## 加载方式

```python
# ✅ 正确
from app.prompts import load_prompt

prompt = load_prompt("swap", "intent")
llm = qwen.with_structured_output(SwapIntentOutput)
result = await llm.ainvoke([
    ("system", prompt.system),
    ("user", user_message),
])

# ❌ 错误：硬编码提示词
SWAP_INTENT_PROMPT = """你是一个互换交易意图识别引擎..."""  # 禁止
```

## 修改工作流

### 需要调整提示词效果时

**不要**：直接改 `app/prompts/**/*.md` 的内容（这是 Dify 原文的拷贝）

**要**：
1. 在 `app/prompts/<category>/<name>_v2.md` 创建新版本（保留 v1 做 A/B）
2. 在代码里用 `load_prompt("swap", "intent_v2")` 测试新版
3. 跑 `python scripts/eval_golden.py` 对比准确率
4. 差异 ≥ 1% 以上才合入

### 从 Dify 重新同步

当 Dify 生产的提示词更新了，要同步过来：

```bash
# 1. 把新版 Dify YAML 放到一个目录
mkdir -p /tmp/new-dify
# 把新 YAML 放进去

# 2. 运行导出脚本
python scripts/export_dify_prompts.py /tmp/new-dify /tmp/new-prompts

# 3. 对比差异
diff -r app/prompts/ /tmp/new-prompts/ | head -50

# 4. 选择性合入（不要一键覆盖）
# 5. 跑 golden set 回归
pytest tests/ -v
python scripts/eval_golden.py tests/fixtures/golden.jsonl
```

## 为新提示词加代码

当业务新增一个 Dify LLM 节点需要迁移：

1. 把 .md 放到正确的 `app/prompts/<category>/` 目录
2. 在 `app/subgraphs/<product>_models.py` 定义对应的 Pydantic Output 模型
3. 在子图里新增一个 `@safe_node` 函数，用 `load_prompt()` + `with_structured_output()`
4. 在 `tests/test_prompts_and_history.py` 加一个加载测试
5. 在 golden set 加至少 2 条端到端 case

## 字符数注意

- `swap/place_order.md` **133K 字符** ≈ 40K tokens，接近 Qwen3-30B 上下文一半
- 长提示词影响延迟（P95 可能 +2-3 秒）
- 评估时记录延迟，若过高考虑拆分提示词为多阶段

## 占位符处理

Dify 原提示词中有 `{{#node_id.var#}}` 占位符（如 `{{#1775913928411.date#}}`）。
这些占位符**保留原样**不替换，LLM 能理解为上下文信息。
不要用 regex 替换它们，会破坏 Dify 原始行为。

## Loader 缓存

`load_prompt()` 内部用 `@lru_cache(maxsize=128)`，应用启动后重复加载是零成本的。
测试中需要重新加载时：`from app.prompts import clear_cache; clear_cache()`
