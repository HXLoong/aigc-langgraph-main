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

### 失败分布（按 category）

- `swap/confirm`: 33/33（全失败）
- `swap/confirm_modify`: 9/9（全失败）
- `swap/confirm_cancel`: 3/3（全失败）

### 失败根因分簇（按 diff 字段重新归类）

把 45 条按 `diff.paths` 归类后，是三个完全不同的问题，不能合并成同一个根因：

| 簇 | 数量 | 占比 | 真实根因 | 归属任务 |
|---|---|---|---|---|
| **A · fixture 字面比对问题** | **10/45** | 22% | `intent` + `product_type` 都对了，仅 `output` diff——fixture 把 `expected.output` 写成语义描述（如"机器人返回互换订单已确认提交..."），harness 字面比对必失败。**不是模型 bug**，是数据集标注问题 | B1.* fixture 校准（PM） |
| **B · product_type 路由错** | **34/45** | 76% | "确认下单 / 确认改单 / 确认撤单"等**裸短语**（无订单号）被路由到 `option`/`option_close`，没进 swap 子图。`intent_route` 节点的规则只有 `rule:order_no→swap`，裸短语命不中→走 LLM 默认路由→大概率被判为 option | C1.3 swap.intent prompt + 路由规则补强 |
| **C · intent LLM 推断错** | **1/45** | 2% | 唯一一条 `swap-004`：`"确认单号 H-20260304-0000001"`（裸订单号无"确认下单"明示词）→ swap_intent 推 `unknown_intent` → fallback | C1.3 swap.intent prompt 补强 |

#### 簇 A 代表样本（fixture 问题）

| case | raw_content | actual.intent | 备注 |
|---|---|---|---|
| swap-005 | "互换 确认下单 H-20260304-ABCD12345678" | `confirm_order`（**正确**） | 仅 output 字面 diff |
| swap-008 | "swap确认修改订单 H-20260304-ABCD12345678" | `confirm_modify_order`（**正确**） | 仅 output 字面 diff |
| swap-100 / 105 / 108 | "确认改单" | `confirm_modify_order`（**正确**） | 仅 output 字面 diff |

#### 簇 B 代表样本（product_type 路由错，最大簇）

| case | raw_content | 期望 product | 实际 product | 实际 intent |
|---|---|---|---|---|
| swap-013 / 015 / 025 / 028 / 030 / ... | "确认下单"（裸短语） | swap | **option** | confirm |
| swap-049 | "确认撤单" | swap | **option_close** | close_order_confirm_cancel |

裸"确认下单/改单/撤单"短语**严重歧义**——这种话术 dify 历史样本里 swap 和 option 都有可能，需要业务方明确：

1. 真实客户输入中是否常出现这种无上下文的裸确认短语？还是 fixture 构造过于极端？
2. 如果是合理输入，**路由规则需要扩**——而不仅仅是改 prompt（LLM 在零上下文下没法稳定判产品类型）。
3. 或者 fixture 把这些 case 标注的 `expected.product_type=swap` 本身值得重审——LLM 选 option 也并非显然错。

#### 簇 C 代表样本（intent 推断错）

| case | raw_content | 期望 intent | 实际 intent |
|---|---|---|---|
| swap-004 | "确认单号 H-20260304-0000001" | confirm_order | **unknown_intent** |

只有这 1 条是 PR 原描述里说的"含订单号但缺'确认下单'明示词"的真问题。

### intent_v2 灰度采样

summary 里按 prompt 版本分桶：

| 版本 | 总数 | PASS | 通过率 |
|---|---|---|---|
| `intent` | 10 | 0 | 0.0% |
| `intent_v2` | 1 | 0 | 0.0% |

**v2 样本仅 1 条**，不足以评估灰度效果；扩大灰度比例的决策需要更大样本，不能基于本报告下结论。

## E3.4 扩展样本：option/cancel 18 条

2026-05-12 后续跑 option/cancel 18 条 case，PASS rate 同样 0%。发现**新簇 D · 意图语义混淆**：

| 簇 | option/cancel 数 | 真实根因 |
|---|---|---|
| 簇 B（裸短语路由错）| 6 (33%) | "撤单"裸短语 → option_close（fixture 期望 option）|
| **簇 D · 意图语义混淆** | 12 (67%) | fixture 标注 `request_cancel_order`，LLM 输出 `cancel_order_request` |

### 簇 D 代表样本

| case | raw_content | 期望 intent | 实际 intent |
|---|---|---|---|
| opt-127 | "撤销" | request_cancel_order | **cancel_order_request** |
| opt-007 | （类似裸短语） | request_cancel_order | cancel_order_request |

`request_cancel_order` 和 `cancel_order_request` 都是合法 OptionIntentionType 值（来自 `app/tools/option_client.py`）：

```python
CANCEL_ORDER_REQUEST = "cancel_order_request"   # 取消下单请求（订单还没成交，作废）
REQUEST_CANCEL_ORDER = "request_cancel_order"   # 请求撤单（订单已成交，撤回）
```

业务语义不同 —— 简短"撤销/撤单"话术下，LLM 选哪个语义是开放问题。需要：

1. 业务方明确 fixture 标注的是哪种场景（订单未成交 vs 已成交）
2. swap.intent prompt 是否能引导 LLM 区分这两种语义
3. 或者 prompt 中要求 LLM 在歧义时输出 `unknown_intent` + 让 fallback 询问用户

## 跨类别样本总览（63 条）

| 类别 | 样本数 | PASS rate | 主要簇 |
|---|---|---|---|
| swap/confirm | 45 | 0% | A 22% + B 76% + C 2% |
| option/cancel | 18 | 0% | B 33% + **D 67%** |
| **合计** | **63** | **0%** | 四簇共存 |

## 结论

阶段 3 E3.1 真后端 harness 跑通 ✅，PASS rate 0%——但 0% 并不等于"模型整体崩了"，而是**四个不同性质问题叠加**：

1. **fixture 字面比对问题**（簇 A，22% of swap/confirm）：需要 B1.* PM 把 `expected.output` 改为可比对结构（intent + 关键字段，不是自然语言描述）。
2. **路由歧义问题**（簇 B，76% of swap/confirm + 33% of option/cancel）：裸"确认下单"/"撤单" 短语命中 keywords.yaml option/option_close 块。判定真正的客户语料分布之前，不应直接调 prompt。详见 [route-ambiguity-decision.md](m3-route-ambiguity-decision.md)。
3. **intent prompt 短板**（簇 C，2% of swap/confirm）：裸订单号 → unknown_intent，可纳入 C1.3 一并处理。
4. **意图语义混淆**（簇 D，67% of option/cancel · 新发现）：fixture 标注与 LLM 输出在两个合法 OptionIntentionType 值之间分歧，需业务方明确 fixture 期望的具体业务场景。

排除簇 A 后，**真模型/路由/标注问题 PASS rate ≈ 0%**，仍远低于 M2 mock baseline (92.5%)；说明真后端 + 真 LLM 模式下意图识别路径有系统性差异，需要 E3.4 错例聚类正式立项。

## 下一步

- **#85 E3.4 错例聚类** 启动，把上述四簇作为初始分类骨架；裸短语样本 + 簇 D 语义混淆送业务方 review。
- **B1.* fixture 校准**（PM 推进）：
  - 簇 A：重新设计 expected.output 比对方式（按 intent + 业务对象状态）
  - 簇 D：明确 fixture 标注的是哪种业务场景（订单未成交 vs 已成交）
- **C1.3 swap.intent v2 prompt 调优**：扩大 v2 灰度采样（目标 ≥ 30 条样本），prompt 补强重点放在簇 C（裸订单号）+ 簇 D（语义区分）。
- **跑全 287 case business_seed 真后端**：留到上述产出后再做（避免重复消耗 token + LLM 调用）。

## 关联

- 关联 Issue #82（本任务）/ #85（E3.4 错例聚类）
- 路线图 C1.3 prompt 调优：[roadmap 4.2 子线 1B](m3-m4-roadmap.md)
- ADR 0003：prompt 版本化 + A/B 灰度
