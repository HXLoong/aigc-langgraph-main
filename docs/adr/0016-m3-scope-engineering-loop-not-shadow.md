# ADR 0016 · M3 范围重定义：工程联调闭环（非 shadow 双跑）

- 状态：已采纳（决策有效；进度与术语按 2026-08-27 现状更新）
- 日期：2026-05-11
- 起源：grill-with-docs 复盘 M2 → M3 转场；修订 ADR 0001 D9 的"M3 = Shadow 双跑"
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #143）
- 作者：图灵科技 + Tony

## 上下文

ADR 0001 D9 原定义 M3 = Shadow 双跑（退出门 `主要意图 diff < 5%；下单/平仓 < 1%`）。M2 收尾复盘发现三个根本性问题：

1. **Dify 不是 ground truth**：迁移动机正是 Dify 的"标的不准/参数 bug/评估缺失"三大缺陷（ADR 0000）——拿 Dify 比 diff 会冤枉 LangGraph 同时美化 Dify。
2. **用户实际目标是工程上线**："尽快完成代码开发"→ mock 跑通 → 对接真实 API → 用例验证，链路里没有 Dify。
3. **退出门应基于 PASS 率**：ground truth = `golden.jsonl expected`（B/C/D 桶），与 Dify 是否 diff 无关。

## 决策

**M3 = 工程联调闭环**，分三段；**Shadow 双跑改名 F4.1 推到 M4**——切流期给业务方"生产真实流量上的 Dify vs LangGraph 对比"作信心参考，**不是合格性判定**。

### 阶段进度（2026-08-27 更新；术语按 roadmap 修订——"anchor 全集"已废弃，统一为 B 桶口径）

| 阶段 | 内容 | 退出门与状态 |
|---|---|---|
| M3.1 · Mock 跑通 | LangGraph 全链路 → mock 后端 → 端到端 | ✅ 完成。真 LLM 84.6%——**未达 85% 阈值**，按 3/4 链路达标 + swap 82% known limitation 放行（详见 `docs/archive/m2/m2-real-llm-final-report.md`；原文"达成 84.6%"与自身阈值矛盾，本次订正）|
| M3.2 · 真后端联调 | `.env` 切真后端域名，read 先 / write 后分批 | ✅ 完成。真后端 `otcoms-test.gf.com.cn` 已联通，roadmap 阶段 2 D2.1–D2.6 全部 closed（原文"⏳ 等 VPN"已过期）|
| M3.3 · 真后端 golden 回归 | B/C/D 桶分别评估 + 错例修 P0/P1 + 业务方 sign-off | ⏳ 进行中（Issue #82–#87 全 OPEN）。⚠️ 退出门原对照值（mock 92.5% / 真 LLM 84.6%）为 Qwen 口径，已被 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 作废——**须在 DeepSeek-V4-pro 上重跑 `scripts/langfuse_eval.py` 重建 baseline 后，退出门才有有效对照** |

M3.x 与 roadmap 阶段号映射（两套编号并行，此处显式对上）：M3.1 = 阶段 1 收尾；M3.2 = 阶段 2（D2.*）；M3.3 = 阶段 3（E3.*）。

## 备选方案

- **A · 保留 Shadow 双跑**：退出门基于不可信的 Dify diff，reject。
- **B · 仅"扩 golden + 真 LLM 跑测"**：漏掉真后端联调（M3.2），部分采纳。
- **C · 工程联调闭环（已选）**：匹配实际目标，渐进可量化，shadow 推 M4。

## 后果（现状口径）

### 积极

- 路径自包含（M3.2 已证明：一行 `.env` 切换即完成）；不依赖 Dify URL/key/字段映射；退出门客观可复现；M4 的 shadow 拿到真生产流量，对业务方决策更有意义。

### 中性 / 风险

- 没有"vs Dify diff 数字"作对外材料，业务方预期需管理。
- swap 链路 known limitation（短指令 quote 利用不足）需在 M3.3 真后端 + DeepSeek 口径下重测。
- baseline 重建（0020）插入在 M3.3 中段，是当前退出门的前置阻塞。

### 工程层产出（M3 启动期记录，含后续演变订正）

- ticker resolver 切 ReAct 模式（`3a8bb73`，env 灰度 + 自动降级）——后续在 `31eeb9e` 进一步简化为纯路径（resolver 现状见 [ADR 0008](./0008-ticker-resolution-as-react-agent.md)）
- httpx 全部 `trust_env=False`（`0498196`，避免 macOS 系统代理拦截）✅ 仍有效
- ~~`tests/conftest.py` 默认 ticker whitelist（`ea40331`，CI 287s → 34s）~~——**已于 `31eeb9e` 回退删除**（违反"禁止 conftest autouse 绕过真实业务路径"的根纪律，见 `tests/CLAUDE.md`；原文的"27s"系笔误，提交信息为 34s）
- shadow_compare 工具（现 512 行，smoke 通过 `5fd693c`）—— 留 M4 F4.1 用

## 引用

- [ADR 0000](./0000-migrate-from-dify-to-langgraph.md) · 迁移动机 / [ADR 0001](./0001-rewrite-app-with-harness-first.md) D8-D9 · 原阶段定义（被本 ADR 修订）
- [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · baseline 作废与重建
- `docs/m3-m4-roadmap.md` · 分阶段任务图 / `docs/archive/m2/m2-real-llm-final-report.md` · M2 收尾报告
