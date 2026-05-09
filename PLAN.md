# 期权链路评估与提示词迭代方案

> Judge：DeepSeek V4 Pro（Anthropic 兼容端点，thinking=4096 tokens）
> 范围：option + option_close 子图，98 条测试 case
> 状态：基础设施完成 ✅，待跑全量基线

---

## 一、已完成

### 基础设施

| 组件 | 文件 | 状态 |
|---|---|---|
| 评估脚本 | `scripts/langfuse_eval.py` | ✅ 单轮/多轮/报告 |
| Dataset 上传 | `scripts/upload_option_dataset.py` | ✅ 98 条 |
| JSONL 转换 | `scripts/convert_testcase_to_jsonl.py` | ✅ CSV→JSONL |
| 本地 golden | `tests/fixtures/option_golden.jsonl` | ✅ 98 条 |
| 操作 skill | `.claude/skills/iterate-option/SKILL.md` | ✅ |

### 数据流

```
Langfuse Dataset (otc-option-golden, 98条)
        │
        ▼
scripts/langfuse_eval.py
  ├── InMemorySaver（不依赖 MySQL checkpoint）
  ├── mock OtcBackendClient（不调真实后端）
  ├── 真实 Qwen LLM（测提示词效果）
  ├── MySQL 标的池直查（172.16.8.27:3306 aigc-test.stock_exchange_sec_data, 14118 条）
  └── DeepSeek V4 Pro Judge（Anthropic 端点, thinking=4096）
        │
        ▼
  自动报告（通过率/失败 case/Judge 理由）
```

### 路由修复

`app/nodes/route.py` — "跟量"关键词与平仓上下文冲突时，路由到 option_close：

```
"跟量" + ("平"/"序号"/"持仓") → option_close（不是 swap）
```

### 标的池

从 HTTP API 切到 MySQL 直查：
- 表：`aigc-test.stock_exchange_sec_data`（14118 条）
- 模糊搜索：`LIKE '%keyword%'` on stock_name/bond_code/stock_english_acronyms/corporate_name
- 配置：`app/config.py` ticker_mysql_* 字段

---

## 二、待做

### Phase 1：全量基线（下一步）
```bash
python scripts/langfuse_eval.py
```
- 跑 98 条，得到各测试功能的通过率
- 区分：路由问题 vs 提示词问题 vs 代码逻辑缺失

### Phase 2：分析并修复
| 问题类型 | 修复方式 |
|---|---|
| 路由错误 | 改 `app/nodes/route.py` 关键词/正则 |
| 提示词不准确 | Langfuse 推新版本，A/B 对比 |
| 代码逻辑缺失 | 改对应节点（如加权限校验） |

### Phase 3：迭代闭环
```
改 → 跑 eval → 看分数涨跌 → 满意打 production 标签
```

---

## 三、关键命令

```bash
# 评估
python scripts/langfuse_eval.py                    # 全量 98 条
python scripts/langfuse_eval.py --filter 期权询价    # 只跑询价
python scripts/langfuse_eval.py --limit 5            # 快速验证
python scripts/langfuse_eval.py --dry-run --limit 5  # 预览

# 数据集
python scripts/upload_option_dataset.py              # 上传到 Langfuse
```

## 四、不做

- 不做 swap / ticker 评估（先聚焦期权）
- 不自部署 Langfuse
- Judge 不用 Qwen（自评不可信）
- 标的池不切回 HTTP API
