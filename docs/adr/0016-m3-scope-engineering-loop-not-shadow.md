# ADR 0016 · M3 范围重定义：工程联调闭环（非 shadow 双跑）

- **Status**: Accepted
- **Date**: 2026-05-11
- **Deciders**: Tony
- **Skill**: 由 grill-with-docs 复盘 M2 → M3 转场时决定
- **修订**: ADR 0001 D9 中 "M3 = Shadow 双跑" 描述

## Context

ADR 0001 D9 原定义 **M3 = Shadow 双跑（2 周）**：LangGraph 与 Dify 并行接收同一份输入，
比对响应差异，退出门 `主要意图 diff < 5%；下单/平仓 < 1%`。

M2 收尾启动 M3 时复盘，发现该计划存在 3 个根本性问题：

### 问题 1 · Dify 不是 ground truth

业务方迁移 LangGraph 的根本动机是 Dify 的 "标的不准 / 参数 bug / 评估缺失" 三大已知缺陷
（ADR 0000）。把 Dify 当 ground truth 比对 diff 会**冤枉 LangGraph 同时美化 Dify** —— 
diff ≠ "LangGraph 错"。

### 问题 2 · 用户实际目标是工程上线，不是等价性证明

用户原话："我的目的是尽快完成代码的开发"。具体流程：
1. Mock API 跑通
2. 对接客户真实 API（Java 后端 + GOATS）
3. 测试用例验证

整个 3 步链路**没有 Dify**。Dify 是被替代的对象，不是 M3 阶段需要"对接"的客户 API。

### 问题 3 · M3 退出门应基于 PASS 率而非 diff 率

ground truth = `golden.jsonl expected` 字段（业务方手写 + LLM 对抗式 paraphrase + 真实流量样本）。
LangGraph 在 golden 上的 PASS 率 ≥ 阈值 → 合格；与 Dify 是否 diff 不影响合格性。

## Decision

**M3 范围从"Shadow 双跑"改为"工程联调闭环"**：

```
M3.1 · Mock API 跑通（已 M2 完成）
  · LangGraph 全链路 → mock_api 8099 → 业务流端到端
  · 退出门：harness anchor 全集 PASS ≥ 85%（达成 84.6%）
  · 状态：✅ 已完成

M3.2 · 真后端联调（外网阻塞中）
  · 切 .env OTC_API_BASE_URL / GOATS_BASE_URL → 真后端域名
  · 灰度按 endpoint 分批切真（read endpoints 先 / write endpoints sandbox 后）
  · 退出门：anchor 全集 PASS ≥ 真后端 baseline，无 5xx crash
  · 状态：⏳ 等业务方提供内网 VPN / 测试环境

M3.3 · Golden 回归（M3.2 后）
  · 真后端环境下跑 anchor + business_seed 全集
  · 退出门：PASS ≥ M3.1 mock baseline（不退化）+ 链路无回归
```

**Shadow 双跑推到 M4 金丝雀阶段**——切流量给 LangGraph 的同时让业务方拿到
"Dify vs LangGraph 在生产真实流量上的输出对比"作为切流加速 / 减速的决策辅助。
**不是合格性判定**，仅是业务方信心建立的"参考第二意见"。

## Considered Options

- **A · 保留原 Shadow 双跑（已选 reject）**：
  退出门基于 Dify diff，Dify 不可信→冤枉 LangGraph + 美化 Dify
- **B · 简化 M3 为"扩 golden + 真 LLM 跑测"（部分采纳）**：
  这是 M3.1 + M3.3 的本质，但漏掉真后端联调环节（M3.2）
- **C · 工程联调闭环（已选）**：
  匹配用户实际目标，分 M3.1/3.2/3.3 渐进，shadow 推 M4

## Consequences

### 积极后果

- **路径自包含**：M3.1 已达成，M3.2/3.3 仅依赖业务方提供内网访问（一行 .env 切换）
- **不依赖 Dify URL/key/字段映射**：业务方少了 3 项 hard 阻塞依赖
- **退出门可量化**：PASS 率 vs golden 客观、可复现，不依赖 Dify 状态
- **Shadow 用得更准**：M4 金丝雀切流时，shadow 拿到的是真生产流量（不是人造样本），diff 数据对业务方决策更有意义

### 中性后果

- **不再有"LangGraph vs Dify diff 数字"**作为 M3 完成的对外公关材料 —— 业务方可能心理预期需要管理（"为什么不和 Dify 比？"）
- **swap 链路 known limitation**（路由层 LLM 利用 quote 不足，PASS 22% 短指令失败）需要在 M3.3 真后端环境再次跑测确认 —— 可能数据会有变化

### 阶段性进度（截至 2026-05-11）

| 阶段 | 状态 |
|---|---|
| M3.1 Mock 跑通 | ✅ 完成（M2 84.6% PASS）|
| M3.2 真后端联调 | ⏳ 等内网 VPN |
| M3.3 真后端 golden 回归 | ⏳ 等 M3.2 |
| Shadow 推到 M4 | ✅ 决定 |

### 工程层产出（M3 启动期）

- ticker resolver 切换 ReAct 模式（commit `3a8bb73`，env 灰度 + 自动降级）
- httpx client 全部加 `trust_env=False`（commit `0498196`，避免 macOS 系统代理拦截）
- `tests/conftest.py` 默认 ticker resolver=whitelist（commit `ea40331`，CI 性能 287s → 27s）
- shadow_compare 工具（375 行，已 smoke test 通过 `5fd693c`）—— 留 M4 用

## 引用

- ADR 0000 · Dify → LangGraph 迁移动机（Dify 三大缺陷）
- ADR 0001 D9 · 原 M3 / M4 阶段定义（被本 ADR 部分修订）
- ADR 0008 · ticker resolver ReAct Agent 设计
- CONTEXT.md · Shadow / Ground truth / M3 范围 术语
- `docs/m2-real-llm-final-report.md` · M2 收尾报告 + known limitation
