---
name: sync-dify-prompts
description: 从最新的 Dify YAML 目录批量同步所有提示词到 app/prompts/，并 diff 旧版，让用户选择合入哪些。使用场景：Dify 生产环境调优后提示词有变化，需要同步到代码库。
argument-hint: <dify-yaml-dir>
allowed-tools: Read, Write, Edit, Glob, Bash
---

# 批量同步 Dify 提示词

## 参数
- `$1` = 包含新版 Dify YAML 的目录

## 执行流程

### Step 1：导出到临时目录
```bash
TEMP=/tmp/dify_sync_$(date +%s)
python scripts/export_dify_prompts.py $1 $TEMP
echo "已导出到 $TEMP"
ls -R $TEMP
```

### Step 2：列出每个新旧文件对比

对 `$TEMP` 下每个新 .md，匹配 `app/prompts/` 下对应旧 .md（按目录+文件名对应关系）：

```bash
for new in $(find $TEMP -name "*.md"); do
    # 尝试推断在 app/prompts/ 下的对应位置
    # 例如 $TEMP/dify主工作流/互换-节点-意图识别.md → app/prompts/swap/intent.md
    # 这里需要人工映射表（见 Step 3）
    ...
done
```

### Step 3：准备映射表

Dify YAML 节点标题 → 项目 prompt 路径：下表列当前活跃映射（以 `app/prompts/` 目录与代码加载点为准）；
已删除不再同步：swap 订单号类 6 个（cancel_order / query_order / confirm_order / confirm_cancel / confirm_modify / 旧合并版 confirm）、
option 4 个 Q- 节点（extract_cancel / extract_cancel_place / extract_confirm_cancel / extract_query）、
option_close 4 个 CO- 节点（cancel_close / confirm_close / confirm_cancel / query_status）、
`option/intent_extract.md`、`option/param_limit.md`、`ticker/completeness.md`。

| Dify 节点标题 | 项目路径 |
|---|---|
| unknown意图兜底识别 | `app/prompts/router/unknown_intent.md` |
| 互换-节点-意图识别 | `app/prompts/swap/intent.md` |
| 互换-节点-下单 | `app/prompts/swap/place_order.md` |
| 互换-选择交易对手 / 互换-选择标的 | `app/prompts/swap/select_counterparty.md` / `select_ticker.md` |
| Excel-互换-请求下单参数解析 | `app/prompts/swap/excel_extract.md` |
| 图片-互换-请求下单参数解析 | `app/prompts/swap/image_extract.md` |
| 互换-图片识别 | `app/prompts/swap/image_ocr.md` |
| 期权-意图识别 | `app/prompts/option/intent.md` |
| 期权-节点-询价 / 下单 / 确认下单 | `app/prompts/option/extract_{inquiry,place,confirm_place}.md` |
| 期权平仓-意图识别 | `app/prompts/option_close/intent.md` |
| 请求下单和确认全部平仓参数提取 | `app/prompts/option_close/place_close.md` |
| 期权平仓-持仓查询参数提取 | `app/prompts/option_close/holding_query.md` |
| 大模型推断对应标的代码 / 标的代码和code的拆分 / 大模型判断标的类型 / 大模型排序并过滤 | `app/prompts/ticker/{infer_code,tokenize,judge_type,rank}.md` |

### Step 4：对每对做 diff

```bash
for mapping in "$TEMP/dify主工作流/互换-节点-意图识别.md:app/prompts/swap/intent.md" ...; do
    new=$(echo $mapping | cut -d: -f1)
    old=$(echo $mapping | cut -d: -f2)
    if diff -q "$new" "$old" > /dev/null; then
        echo "✓ 无变化：$old"
    else
        echo "≠ 有变化：$old"
        diff "$old" "$new" | head -30
        echo ""
    fi
done
```

### Step 5：生成变更报告

```markdown
# Dify 提示词同步报告

源目录：$1
同步时间：<now>

## 变更摘要
- 有变更：N 个
- 无变更：M 个
- 新增：K 个
- 可能需要手工归类：L 个

## 详细变更列表

### swap/intent.md
<diff 摘要，前 30 行>
**建议**：<对齐业务反馈，提示词改动幅度评估>

### swap/place_order.md
...
```

### Step 6：让用户决定（重要）

**不要自动合入**。列出每个有变化的文件，问用户：
1. 这些改动对应 Dify 的什么业务调整？
2. 哪些要合入？哪些要保留旧版做 A/B？
3. 合入后需要跑哪些 golden case 回归？

### Step 7：按用户决策应用

对选择合入的文件：
```bash
# 备份旧版
cp app/prompts/swap/intent.md app/prompts/swap/intent.md.bak.$(date +%Y%m%d)

# 合入新版
cp $TEMP/dify主工作流/互换-节点-意图识别.md app/prompts/swap/intent.md
```

### Step 8：回归验证

```bash
# 加载测试（确认没破坏 md 格式与 spec 契约）
pytest tests/test_prompt_loader.py tests/test_prompt_spec.py -q

# 回归测试
pytest tests/ -q

# fixture 评估（建议手动跑，需要服务运行中）
# python scripts/langfuse_eval.py --local tests/fixtures/categories
```

### Step 9：清理
```bash
rm -rf $TEMP
```

## 禁止

- 自动覆盖（必须用户 review）
- 忘记备份旧版
- 跳过回归测试
- 同步后不让用户知道变更点

## 特殊情况

- **找不到对应项目路径**：新 Dify 节点标题未在映射表，列出可能的归类，让用户裁决
- **节点数量减少**：Dify 删了某个节点，不要自动删我们的 .md，保留并标注"可能废弃，待确认"
