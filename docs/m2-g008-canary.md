# g008 修复 · swap.intent v2 灰度上线说明

> 案例：`g008` raw_content="swap确认修改订单 H-20260304-ABCD12345678"
> 期望意图：`confirm_modify_order`
> v1 实际行为：偶发误判为 `place_order_request`（LLM 抖动，Day 19 复现率约 30%）

## 根因分析

v1 prompt 中存在两条规则的潜在冲突，LLM 推理时被错误优先级吸引：

1. **第 132 行**：`confirm_modify_order:仅当 raw_content 明确包含"确认改单"或"确认修改"且语义肯定时触发`
2. **第 141 行**：`用户说"改为"、"修改"、"改单"、"调整"...时,统一识别为 place_order_request`

g008 的 raw_content `"swap确认修改订单 H-..."` 同时命中两条：
- 含整体短语 `"确认修改"` → 应优先 confirm_modify_order
- 含子串 `"修改"` 与订单号 → 易被参数调整规则吸引

LLM 偶尔被订单号/参数关键词的"具象化"信号引导走 place_order_request。

## v2 修复策略

不改 v1（保留生产基线），新建 `intent_v2.md` 添加**两层冲突仲裁规则**：

### 在第六节 CONFIRM_MODIFY_ORDER 处加强

```diff
+ 【v2 关键规则 · 修 g008 偶发误判】:
+ - 绝对优先级:整体短语"确认改单"/"确认修改"四字命中 → 直接 confirm_modify_order,
+   忽略所有参数调整规则。
+ - 不要被订单号/参数关键词干扰:即使 raw_content 同时含 H-XXX 订单号、
+   英文前缀(swap/trs)、参数关键词,只要含"确认改单"或"确认修改",一律 confirm_modify_order。
+ - 正例 / 反例（含 g008 复现 case）...
```

### 在【参数调整/补充类统一规则】处加例外

```diff
+ 【v2 强化 · 冲突仲裁】例外:若 raw_content 含整体短语"确认改单"或"确认修改",
+ 绝对优先走 confirm_modify_order,本规则不适用。
+
+ 区分原则:
+   * "修改" / "改" / "改单" 单独出现 → place_order_request(本规则)
+   * "确认改单" / "确认修改" 作为完整四字短语出现 → confirm_modify_order(优先级高)
```

## 灰度配置（5%）

`app/prompts/_versions.yaml`：

```yaml
overrides:
  swap.intent:
    versions:
      - name: intent       # v1 生产基线
        weight: 0.95
      - name: intent_v2    # v2 修 g008
        weight: 0.05
```

**分流稳定性**：sha256(conversation_id) 前 8 位 hex 取模，同一会话永远命中同一版本。

## 评估流程

### 1. 灰度期监控

trace 查询字段：`llm_output.prompt_name`

```sql
-- LangFuse 按版本分组统计 PASS 率
SELECT
  json_extract(llm_output, '$.prompt_name') as version,
  intent,
  COUNT(*) as samples
FROM swap_intent_traces
WHERE timestamp > now() - INTERVAL 24 HOUR
GROUP BY version, intent
```

### 2. 退出门

灰度上线 7 天后评估：

| 指标 | v1 基线 | v2 目标 | 决策 |
|---|---|---|---|
| g008 同类 case PASS 率 | ~70% (偶发误判) | ≥ 95% | v2 ≥ 95% → 扩流量 |
| 总体 PASS 率 | 100% (30/30) | 不下降 | v2 PASS ≥ v1 → 安全 |
| P95 延迟 | baseline | +10% 容忍 | 超 10% → 回滚 |

### 3. 扩流量阶梯

```
5% （当前）→ 25% → 50% → 100%
            ↑ 每阶段稳定 24h 后推进
```

### 4. 完结清理（v2 全量稳定 7 天后）

1. 删 `app/prompts/swap/intent.md`（旧 v1）
2. 重命名 `intent_v2.md` → `intent.md`
3. 移除 `_versions.yaml` 中 `swap.intent` override
4. 更新 trace 标注 v3 为新基线（如未来再迭代）

## 紧急回滚

```bash
# 方式 A：env 强制全量 v1
export OTC_PROMPT_SWAP_INTENT_VERSION=v1

# 方式 B：删 _versions.yaml override
# 方式 C：把 weight 改为 1.0/0.0
```

任一方式生效后，重启进程或调用 `clear_cache()` 即可。

## 测试覆盖

| 测试文件 | 覆盖 |
|---|---|
| `tests/test_prompt_versioning.py` | 灰度机制本身（18 用例） |
| `tests/test_swap_intent_v2_canary.py` | v2 文件加载 + 5% 分流 + trace 记 prompt_name |

真 LLM 评估留给业务方拨测 / shadow 阶段（pytest 不调外部 LLM）。

## 相关参考

- ADR 0003 — 提示词版本化采用"同目录文件并存"
- ADR 0001 D5 — Dify 重构期内可改写
- `docs/m2-prompt-ab-testing.md` — 灰度机制操作手册
