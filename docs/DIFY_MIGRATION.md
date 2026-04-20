# Dify → LangGraph 迁移指南

## 已完成的映射

### 文件对应关系

| Dify YAML | 迁移到 |
|---|---|
| `Dify主工作流.yml`（65 节点） | `app/graphs/main_graph.py` + `app/subgraphs/*.py` |
| `期权工具.yml`（15 节点） | `app/subgraphs/option.py` |
| `互换工具.yml`（4 节点） | `app/subgraphs/swap.py` + `app/tools/otc_backend.py` |
| `标的智能化推断和分词工具.yml`（24 节点） | `app/subgraphs/ticker.py` + `ticker_tools.py` |
| `标的相关性排序工具.yml`（7 节点） | `app/subgraphs/ticker_tools.py::llm_rank_candidates` |

### 节点类型映射

| Dify 节点类型 | LangGraph 等价物 |
|---|---|
| `start` | `StateGraph.set_entry_point()` |
| `end` / `answer` | `END` 常量 |
| `code` (Python) | 普通 Python 节点函数 |
| `llm` | 节点内调用 `ChatOpenAI.with_structured_output()` |
| `if-else` | `add_conditional_edges()` + 纯函数路由 |
| `tool` | 子图嵌入或 `@tool` 装饰 |
| `http-request` | `httpx.AsyncClient` via `OtcBackendClient` |
| `variable-aggregator` | 不需要，State TypedDict 天然合并 |
| `assigner` | `Annotated[X, reducer]` |
| `iteration` | `Send` API 或子图循环 |

### 提示词对应

全部 21 个真实 Dify 提示词在 `app/prompts/`：

| Dify 节点标题 | 项目路径 |
|---|---|
| 互换-节点-意图识别 | `app/prompts/swap/intent.md` |
| 互换-节点-下单 | `app/prompts/swap/place_order.md` |
| 互换-节点-确认下单 | `app/prompts/swap/confirm_order.md` |
| 互换-节点-撤单 | `app/prompts/swap/cancel_order.md` |
| 互换-节点-确认撤单 | `app/prompts/swap/confirm_cancel.md` |
| 互换-节点-确认改单 | `app/prompts/swap/confirm_modify.md` |
| 互换-节点-查询订单 | `app/prompts/swap/query_order.md` |
| Excel-互换-请求下单参数解析 | `app/prompts/swap/excel_extract.md` |
| 图片-互换-请求下单参数解析 | `app/prompts/swap/image_extract.md` |
| 互换-图片识别 | `app/prompts/swap/image_ocr.md` |
| 期权平仓-意图识别 | `app/prompts/option_close/intent.md` |
| 请求下单和确认全部平仓参数提取 | `app/prompts/option_close/place_close.md` |
| 期权平仓-持仓查询参数提取 | `app/prompts/option_close/holding_query.md` |
| 确认平仓 | `app/prompts/option_close/confirm_close.md` |
| 撤单参数提取 | `app/prompts/option_close/cancel_close.md` |
| 确认撤单参数提取 | `app/prompts/option_close/confirm_cancel.md` |
| 平仓订单查询 | `app/prompts/option_close/query_status.md` |
| 大模型推断对应标的代码 | `app/prompts/ticker/infer_code.md` |
| 大模型识别标的完整性 | `app/prompts/ticker/completeness.md` |
| 互换-标的代码和code的拆分 | `app/prompts/ticker/tokenize.md` |
| 大模型排序并过滤 | `app/prompts/ticker/rank.md` |

## 同步新 Dify 版本

### 方式 1：用 Claude Code skill
```
/sync-dify-prompts /path/to/new-dify-yamls/
```

### 方式 2：手动
```bash
# 1. 导出
python scripts/export_dify_prompts.py /path/to/new-dify/ /tmp/new-prompts/

# 2. diff
for new in $(find /tmp/new-prompts -name "*.md"); do
  old="app/prompts/$(echo $new | sed 's|/tmp/new-prompts/||')"
  [ -f "$old" ] && diff -q "$old" "$new"
done

# 3. 选择性合入，备份旧版
# 4. 跑回归：pytest tests/ + python scripts/eval_golden.py
```

## 迁移未完成的部分

### 图片/Excel 解析的下游
- `app/subgraphs/swap.py::parse_image` 实现了 OCR，但下游还是走通用的 `extract_place_order`
- Dify 有独立的 `图片-互换-请求下单参数解析`（109K 字符）和 `Excel-互换-请求下单参数解析` 提示词
- 这两个 .md 已导入 `app/prompts/swap/image_extract.md` 和 `excel_extract.md`，但代码还没接入

**待办**（stage 4 完成）：
1. 让 `extract_place_order` 根据 modality 选择不同提示词
2. 或新增 `extract_from_image` / `extract_from_excel` 节点

### 期权子图的精细化
- 当前 `option.py` 用一个 `extract_option` 节点粗略处理所有意图
- Dify 原 `期权工具.yml` 有 15 个节点，包含参数校验、存量兼容、建仓校验等
- 建议用 `subgraph-builder` agent 拆分

### 历史消息的细粒度
- 当前 `load_history_from_checkpoint` 直接从 checkpoint 反向回溯
- Dify 用 `assigner + history_query_str` 精确管理，保留了意图历史
- 差异可能导致某些多轮场景（如"继续问之前那个"）出错

## 对齐检查清单

发布前跑一遍：

- [ ] 跑 `dify-reviewer` agent 完整审查
- [ ] `python scripts/eval_golden.py` 准确率 ≥ 98%
- [ ] `python scripts/shadow_compare.py` 生产流量采样 200+ 条一致率 ≥ 99%
- [ ] 手工验证 10 条高频指令
- [ ] 验证 `interrupt_before` 在实际下单前生效
