# 标的识别子图重构记录

## 变更日期：2026-04-30

## 问题

`app/subgraphs/ticker.py` 是全项目唯一使用 ReAct Agent 的模块，存在三个核心问题：

1. **延迟过高**：每次查询 LLM 调用 5-7 轮，单个标的解析动辄 10-99s，13 条测试总耗时 ~454s
2. **不稳定**：同一个查询不同轮次结果不同（如"腾讯控股"有时命中有时 0 结果），Agent 决策路径不可预测
3. **架构不一致**：其他子图（swap/option/close）都用的固定节点 `StateGraph`，只有 ticker 用 ReAct

## 修改内容

### 1. 新增 `app/subgraphs/ticker_models.py`

定义 `TokenizeOutput` Pydantic 模型，用于 LLM 分词的结构化输出：

```python
class TokenizeOutput(BaseModel):
    keywords: list[str]           # 提取到的关键词
    needs_refinement: bool        # 质量自检：是否需要重新提取
```

### 2. 重构 `app/subgraphs/ticker.py`（核心变更）

**从 ReAct Agent → 固定拓扑 StateGraph**

旧架构：
```
ReAct Agent（5 个工具，LLM 自主决策调用顺序，5-7 轮 LLM）
```

新架构（5 节点固定图）：
```
START → [cache check] → tokenize_keywords (LLM #1)
                              ↓
                       [quality check]
                       ↙              ↘
              retokenize (LLM #2)   search_candidates (API，非 LLM)
                       ↘              ↙
                              ↓
                       [candidate count]
                       ↙              ↘
              rank_candidates      finalize_tickers
              (LLM, >6 候选)       (≤6, 直接确认)
                       ↘              ↙
                              ↓
                             END
```

LLM 调用从 5-7 次降到 1-3 次。

### 3. 新增 `app/prompts/ticker/tokenize_v2.md`

基于 Dify 原版 `tokenize.md` 改写，关键改动：

- **保守 → 宽松**："宁可少提取"改为"宁可粗不要漏"，适配固定图管线（后面有 API 和 rank 兜底）
- **结构化列表 → 非结构化文本**：原版假设输入是预分割的标的列表，v2 直接处理原始用户消息
- **新增 `needs_refinement` 判断标准**：明确何时触发重提取
- **新增场景覆盖**：期货描述去噪增强、多词英文名整体提取、`$BTC` 处理、`0024 - 15` 横线分隔

### 4. 更新 `app/subgraphs/swap.py` 和 `option.py`

调用方从函数式 → 子图编译式，与项目其他子图统一：

```python
# 旧
from app.subgraphs.ticker import build_ticker_agent
g.add_node("ticker_identify", build_ticker_agent())

# 新
from app.subgraphs.ticker import build_ticker_graph
g.add_node("ticker_identify", build_ticker_graph().compile())
```

## 效果

| 指标 | 旧版 ReAct | 新版 固定图 | 提升 |
|------|-----------|------------|------|
| 总耗时（13条） | ~454s | **99s** | **4.6x** |
| 平均延迟 | ~35s | **7.7s** | **4.5x** |
| 命中率 | 8/13 (62%) | **11/13 (85%)** | +23% |
| 最慢查询 | 99.7s | 23.5s | 4.2x |
| LLM 调用/查询 | 5-7 次 | 1-2 次 | 3-5x |

## 未命中的 2 条

- **UXK6**：API 库无此标的覆盖
- **T 99901.SZ**：v2 分词把 "T" 误提取为关键词，污染了搜索（已知回归，暂不处理）
