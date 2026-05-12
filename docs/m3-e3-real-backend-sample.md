# E3.1 真后端 harness PASS rate 小样本评估

> 2026-05-12 · 阶段 3 启动 · 仅跑 swap/confirm 类别 45 条 case 作为可行性验证

## 执行命令

```bash
python -m harness run --category swap/confirm --out .harness-runs/e3_1_sample
```

## 环境

- 真后端：`otcoms-test.gf.com.cn`（D2.* 已验证可达）
- LLM：开发期 Qwen（`qwen3-30b-a3b` + `qwen3.5-35b-a3b` thinking + VL）
- ticker resolver：真 GOATS 模式（不加 `--mock-ticker`）

## 结果

| 指标 | 值 |
|---|---|
| 总 case | 45 |
| PASS | 0 |
| FAIL | 45 |
| PASS rate | **0.0%** |

### 失败聚类

- `swap/confirm`: 33/33（全失败）
- `swap/confirm_modify`: 9/9（全失败）
- `swap/confirm_cancel`: 3/3（全失败）

### 根因

绝大部分失败是 **swap_intent LLM 推断错误**：

| case | raw_content | 期望 intent | 实际 intent |
|---|---|---|---|
| swap-004 | "确认单号 H-20260304-0000001" | confirm_order | **unknown_intent** |
| swap-005 | "互换 确认下单 H-20260304-ABCD12345678" | confirm_order | unknown_intent |
| ... | ... | ... | ... |

**问题**：raw_content 中含订单号但缺"确认下单"明示词时，LLM 推断为 `unknown_intent`，不进 swap_confirm 子节点 → 走 fallback render → 输出"我没完全理解你的意思..."

**关联**：
- C1.3 swap.intent v2 prompt 调优在阶段 1 被跳过（[roadmap §4.2](../docs/m3-m4-roadmap.md#4.2)）
- 实际上 intent_v2.md 已存在 + 5% 灰度已实现，真 LLM 行为在 v2 下可能改善

## 结论

阶段 3 E3.1 真后端 harness 跑通 ✅，但 **PASS rate 远低于 M2 mock baseline (92.5%)**。

需要：
1. **#85 E3.4** 错例聚类：把 45 条 swap/confirm 失败作为最大错例聚类，分析是否：
   - swap.intent prompt 需要补强（隐含订单号 → confirm_order）
   - 或者 intent_v2 灰度比例需要扩大
2. **数据集校准**：fixture 的"期望 intent" 是基于 M2 mock 行为标注的，真后端/真 LLM 行为可能与 fixture 不完全等价 → 部分 case 需要业务方 review fixture 标注是否准确

## 下一步

- 跑全 287 case business_seed 真后端会消耗大量 LLM token + 真后端调用 → 建议先做小样本聚类分析（本报告）
- **#85 E3.4** 启动后再决定是否值得跑全集
- C1.3 swap.intent v2 灰度比例可能需要重新评估
