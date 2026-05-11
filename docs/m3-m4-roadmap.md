# M3 / M4 路线图 · Dify → LangGraph 切换全量上线

> 编制日期：2026-05-11
> 编制人：Tony（与开发团队对齐版）
> 状态：**讨论稿**，待团队 review 后定版
> 关联 ADR：0001 D9（旧 M3 定义）/ 0016（M3 范围重定义为工程联调闭环）

---

## 0. 文档目的

本文档把"Dify 工作流 → LangGraph 切换并在客户现场上线"这一业务目标，拆解成从今天到全量上线再到二期持续优化的端到端任务图，供团队认领、排期、跟踪。

**不局限于 GitHub Issue**：涵盖 GitHub 上没单独建 issue 但上线前必须完成的工作（部署能力、可观测性、on-call、培训等）。

**前提澄清**（2026-05-11 与 Tony 对齐）：

- 客户现场已进入，**网络问题已解决**——不存在 VPN 阻塞
- 客户内网 MySQL 版本、Qwen API 可达性、企微回切开关、数据合规、AI 标注员角色等历史风险点**全部不再是 P0 阻塞**，按常规配置工作推进

---

## 1. 业务目标拆分（6 个交付面）

把"切换 Dify"拆成 6 个必须完成的交付面：

| # | 交付面 | 关键产出 |
|---|---|---|
| 1 | **代码完整性** | 24 节点 + P2 辅助节点 + 真后端契约对齐 |
| 2 | **数据集完整性** | B 桶（业务方种子）/ C 桶（LLM paraphrase）/ 集成集 / D 桶初版（客户真实样本） |
| 3 | **客户现场部署能力** | 私有化包 / LangFuse self-hosted / MySQL 校验 / 模型路由 / 一键部署脚本 |
| 4 | **联调与回归** | 真后端联调 + golden 全集回归 + 现场 smoke + 业务方 sign-off |
| 5 | **可观测 + 运维** | 监控指标 / 告警 / on-call SOP / 紧急回滚预案 |
| 6 | **上线策略** | Shadow 双跑（M4 第二意见）+ 金丝雀切流（10/30/100%）+ 全量验收 |

---

## 2. 任务总图（按依赖排序）

```
阶段0 解阻塞   →  阶段1 数据+代码补全(5 条子线并行)  →  阶段2 真后端联调
                                                              ↓
                                                      阶段3 回归+现场smoke
                                                              ↓
                                                      阶段4 Shadow+金丝雀
                                                              ↓
                                                      阶段5 全量上线+稳定期
                                                              ↓
                                                      阶段6 二期持续优化
```

**关键路径总长**：阶段 0 (1d) + 阶段 1 (2w) + 阶段 2 (1w) + 阶段 3 (1w) + 阶段 4 (2w) + 阶段 5 (4w 稳定观察) ≈ **6-7 周到全量上线**，再加 4 周稳定期。

---

## 3. 阶段 0 · 立即解阻塞（0.5–1 天，串行，最高优先级）

| 任务 ID | 内容 | Owner | 依赖 | 估时 |
|---|---|---|---|---|
| **A0.1** | 诊断 PR #41 CI failure，拉 GitHub Actions log，定位是 pytest / ruff / mypy 哪条挂；修绿 | 资深开发（#25） | 无 | 0.5d |
| **A0.2** | PR #41 review + merge → main | Tony + #25 | A0.1 | 0.5d |

**理由**：M2 还没合入 main。所有后续工作都基于 ticker 子图 + 92.5% pass rate 的 golden 集。不合则后续开发分散在 feature/m2-ticker-subgraph 上，merge 越来越难。

**退出门**：PR #41 全绿 + merged + main 标签 v0.2.0-m2-complete。

---

## 4. 阶段 1 · 数据集与代码补全（1–2 周，5 条子线并行）

阶段 0 完成后立即铺开。子线之间无依赖。

### 4.1 子线 1A · 数据集体系建设

| 任务 ID | 内容 | Owner | 估时 |
|---|---|---|---|
| **B1.1** | ticker fixture 补到 ≥ 30 条（当前 20 条），覆盖港股 / 期货 / 同名歧义 / 缩写 / 复合标的，完成 #20 退出门 | #26 | 1d |
| **B1.2** | B 桶（业务方种子）按意图均衡，每意图 ≥ 6 条，目标 ≥ 200 条 | PM + 实习生（#27） | 3-5d |
| **B1.3** | C 桶（LLM paraphrase）扩到 ≥ 100 条，业务方 sign-off pass 才合入 | #25 + #27 | 2-3d |
| **B1.4** | **集成测试集**：多轮对话 + interrupt 恢复 + cascade fallback 端到端场景，10-20 条 | #25 | 2d |
| **B1.5** | 客户真实输入样本（**D 桶初版**）：业务方提供 30-50 条历史真实话术 | Tony 协调 | 1-2d |
| **B1.6** | 数据集质量审计脚本：自动检测 expected 字段缺失 / intent 枚举非法 / 重复 case | #27 | 1d |

### 4.2 子线 1B · 剩余代码节点

| 任务 ID | 内容 | Owner | 估时 |
|---|---|---|---|
| **C1.1** | **#29 swap.hand_to_share** P2 节点 + 5 条 golden | #26 | 2-3d |
| **C1.2** | swap 其余 P2：`place_order_image` / `place_order_excel` / `image_recognize` / `cancel_extract` | #26 | 4-5d |
| **C1.3** | swap.intent v2 prompt 调优 — 修 g008 短指令路由（M2 known limitation，PASS 22%） | #25 | 1-2d |
| **C1.4** | swap.place_order 133K token prompt 瘦身（响应延迟治理） | #25 | 2d |

### 4.3 子线 1C · 可观测性 + 监控基础设施（上线前必须）

| 任务 ID | 内容 | Owner | 估时 |
|---|---|---|---|
| **C1.5** | 业务指标埋点：每意图响应延迟 / PASS 率 / 节点错误 / fallback 触发率 / HITL 触发率 | #25 | 2d |
| **C1.6** | 告警：5xx crash / cascade fail / HITL 长时间未恢复 / LLM 失败率阈值 | #25 | 1-2d |
| **C1.7** | LLM 成本监控：tokens 累计 / 按模型 / 按节点拆分 | #25 | 1d |
| **C1.8** | trace 完整性：节点级 trace 写 MySQL `node_trace` 表 + LangFuse 双写 | #25 | 1d |

### 4.4 子线 1D · 客户现场部署能力

| 任务 ID | 内容 | Owner | 估时 |
|---|---|---|---|
| **C1.9** | 客户环境调研报告 `docs/customer-env-assessment.md`（含 MySQL 版本、Java 后端可达性、模型 API 网络）| Tony + #25 | 1d |
| **C1.10** | 大模型方案确认：客户能否访问云 Qwen / 是否走本地化模型 | Tony | 已确认（按 Tony 同步） |
| **C1.11** | LangFuse self-hosted 客户内网部署：docker-compose + image 拉取 + 数据持久化 | #25 | 1-2d |
| **C1.12** | `.env.customer.template` + 私有化部署文档 `docs/deploy/customer-private.md` | #25 | 1d |
| **C1.13** | 一键部署脚本 `scripts/deploy-customer.sh`（含 smoke 自检） | #25 | 1-2d |
| **C1.14** | 离线依赖包：pip wheel 全集 + 必要 docker image 离线包（应对客户网段封禁） | #25 | 1d |

### 4.5 子线 1E · 流程与文档（与 1C 配套）

| 任务 ID | 内容 | Owner | 估时 |
|---|---|---|---|
| **C1.15** | 故障 SOP：cascade fail / LLM 超时 / 后端 5xx / Checkpointer 失败 各自诊断步骤 | #25 | 1d |
| **C1.16** | on-call runbook：值班流程 / 回滚步骤 / 紧急切回 Dify 开关（流量层）| Tony + 客户 IT | 1d |
| **C1.17** | 业务方培训资料补完：以 `docs/training/` 为底，加客户场景示例 | Tony + PM | 1-2d |
| **C1.18** | 安全审计：API key 轮转流程 / secret 不入 git 校验 / 接入审计日志 | #25 | 1d |

**阶段 1 退出门**：

- 数据集 B+C 桶按桶达标 + 集成集 ≥ 10 条 + D 桶初版 ≥ 30 条
- swap P2 节点至少 hand_to_share 完成（其余可推到上线后）
- 监控 + 告警 + on-call runbook 联通跑通一次 dry run
- 客户私有化部署包能在客户测试环境一键起来 + smoke 自检通过

---

## 5. 阶段 2 · 真后端联调（1 周）

依赖：阶段 1 子线 1B/1C/1D 完成 + 客户真 Java 后端可达地址到位。

| 任务 ID | 内容 | Owner | 依赖 | 估时 |
|---|---|---|---|---|
| **D2.1** | 三个 client（Option/Swap/Ticker）切真后端 endpoint，按 ADR 0016 灰度：**read endpoints 先 → write endpoints sandbox 后** | #25 | C1.9 | 1d |
| **D2.2** | 真后端字段对齐验证：用 1 条 anchor case 跑通，对照 `docs/api-contracts/java-backend.md` 校验每字段 | #25 | D2.1 | 1-2d |
| **D2.3** | 不可达降级：真后端 timeout / 5xx → 自动退到 mock 或友好 fallback | #25 | D2.1 | 1d |
| **D2.4** | ticker 真 GOATS 联调：`securities-instrument/select` 真接 + 多命中分差 / HITL 信号真实回路 | #25 | D2.1 | 1-2d |
| **D2.5** | InferCode 动态 prompt 片段（ADR 0013）真后端拉取：`counterparty/info/instrument-inference-prompt` + 5 分钟 LRU 缓存 + 不可达降级 | #25 | D2.1 | 1d |
| **D2.6** | 健康检查端点 `/health` + `/ready`（依赖 MySQL / LangFuse / Qwen / Java 后端 4 个上游） | #25 | C1.5 | 0.5d |

**阶段 2 退出门**：anchor 全集真后端跑通无 5xx；不可达降级路径单测 + 演练通过；健康检查在客户测试环境绿。

---

## 6. 阶段 3 · 真后端 Golden 回归 + 现场 Smoke（3-5 天）

依赖：阶段 2 完成 + 阶段 1 数据集就位。

| 任务 ID | 内容 | Owner | 依赖 | 估时 |
|---|---|---|---|---|
| **E3.1** | 真后端跑 anchor 全集（B 桶）→ PASS ≥ M3.1 mock baseline | #25 | D2.* | 0.5d |
| **E3.2** | 真后端跑 business_seed 全集 → 按桶达标（B ≥ 90% / C ≥ 80%） | #25 | D2.* | 0.5d |
| **E3.3** | 真后端跑客户真实输入样本（D 桶初版） | #25 | B1.5 | 0.5d |
| **E3.4** | 错例聚类 + 根因分析：按 `suspected_node` 归类，找共性 bug → 修补迭代 | #25 + #26 | E3.1-3 | 2-3d |
| **E3.5** | 现场 smoke checklist `docs/customer-smoke-checklist.md` 落地 + 与客户 Java 后端联调（真实下单/撤单/查询） | Tony + #25 | E3.4 | 1-2d |
| **E3.6** | 业务方培训 + 业务方现场 sign-off | Tony + PM | E3.5 | 1d |

**阶段 3 退出门**（M3.3 + #33 阶段 3-4 合并退出门）：

- anchor 全集真后端 PASS ≥ mock baseline，不退化
- 业务真实流程（下单/撤单/查询/平仓）人工 dry run 全绿
- 业务方书面 sign-off

---

## 7. 阶段 4 · M4 金丝雀 + Shadow 双跑（2 周）

依赖：阶段 3 sign-off。

**Shadow 工具（commit `5fd693c`）作为"第二意见"**——不是合格性判定（ADR 0016）。它的作用是让业务方看到"同样的输入下，LangGraph 和 Dify 输出的差异"，作为加速/减速切流的辅助参考。

| 任务 ID | 内容 | Owner | 估时 |
|---|---|---|---|
| **F4.1** | Shadow 双跑：生产真实流量同时投 LangGraph + Dify，按 LangFuse trace 字段级 diff | #25 | 持续 |
| **F4.2** | 流量切流 10%：观察 24h，监控指标对比 Dify baseline | Tony + #25 | 1d 准备 + 1d 观察 |
| **F4.3** | 流量切流 30%：观察 2-3 天 | Tony + #25 | 3d |
| **F4.4** | 流量切流 100%：观察 1 周，记录回归 | Tony + #25 | 7d |
| **F4.5** | 回滚预案：业务参数差异 > 阈值 → 自动切回 Dify 开关 + on-call 流程 | #25 + 客户 IT | 1-2d 准备 |
| **F4.6** | 灰度期错例修复 + 提示词热更（用 LangFuse Prompt 在线版本切换） | #25 | 持续 |
| **F4.7** | 业务方最终验收 + Dify 下线决策 | Tony + PM | 1-2d |

**阶段 4 退出门**：100% 流量稳定 7 天无 P0；业务方书面同意 Dify 下线。

---

## 8. 阶段 5 · 全量上线后稳定期（4 周观察）

| 任务 ID | 内容 | Owner |
|---|---|---|
| **G5.1** | 持续监控 + 月度回归报告（金融场景必须） | #25 |
| **G5.2** | Dify 工作流停用 + 资产归档（保留 `dify/yaml/` 作为历史） | Tony |
| **G5.3** | 客户最终验收报告 + 项目阶段性总结 | Tony + PM |

---

## 9. 阶段 6 · 二期持续优化（上线稳定后启动）

| 任务 ID | 内容 | GitHub | 估时 |
|---|---|---|---|
| **H6.1** | 评估循环自动化：错例聚类 → 改进 patch → A/B 评估 | #35 | 3-6w |
| **H6.2** | Agentic Memory：跨会话经验记忆 + 客户级隔离 | #36 | 4-8w |
| **H6.3** | 回流集自动化：生产流量 → D 桶 + 人工标注 UI + 客户内网合规同步 | #37 | 6-10w |
| **H6.4** | Prompt 持续调优 + 模型升级路径（Qwen / DeepSeek / Claude 多模型矩阵） | — | 持续 |

二期启动前 Tony 与客户对齐"AI 数据标注员"角色（#37 前置）。

---

## 10. 关键依赖链（最长路径可视化）

```
A0.1 PR#41 修绿  →  A0.2 merge
                    ↓
                    ├─ B1.1-1.6 数据集（5d）
                    ├─ C1.1-1.4 代码节点（4-5d）
                    ├─ C1.5-1.8 可观测性（4-5d）
                    ├─ C1.9-1.14 部署能力（5d）
                    └─ C1.15-1.18 流程文档（3-4d）
                          ↓ (上述并行 ≈ 2w)
                    D2.1-2.6 真后端联调（1w）
                          ↓
                    E3.1-3.6 真后端回归 + 现场 smoke（3-5d）
                          ↓
                    F4.1-4.7 Shadow + 金丝雀（2w）
                          ↓
                    G5.* 全量上线 + 稳定期观察（4w）
                          ↓
                    H6.* 二期持续优化
```

**关键路径**：A0 (1d) → 阶段 1 (10d) → 阶段 2 (5d) → 阶段 3 (5d) → 阶段 4 (10d) ≈ **31 个工作日 ≈ 6-7 周**到全量上线。

---

## 11. 角色与认领建议

| 角色 | 主要任务 | GitHub Issue |
|---|---|---|
| **Tony**（主导 + 商务） | 客户协调 / #33 Epic / 现场 smoke / sign-off / 灰度决策 | #33 / #34 |
| **资深开发 #25** | PR #41 修绿 / 真后端联调 / 部署能力 / 可观测性 / 阶段 2-4 主推手 | #25 + #29 #30 reviewer |
| **一年经验 #26** | swap P2 节点（hand_to_share 等）+ ticker fixture 扩充 | #29 |
| **实习生 #27** | B/C 桶 golden 扩充 + 数据质量审计脚本 + cascade 单测 | #31 #32 |
| **PM** | 业务方 case 收集 / D 桶真实样本协调 / 业务方培训组织 | — |

---

## 12. 风险登记（已收敛）

历史风险点中已与 Tony 在 2026-05-11 对齐**全部不再是 P0 阻塞**：

| 历史风险 | 当前状态 |
|---|---|
| ~~客户内网 VPN 申请超时~~ | 客户现场已进入，网络已通 |
| ~~MySQL 版本不符 ADR 0009~~ | 客户环境可解决 |
| ~~Qwen 网络可达性~~ | 已确认 |
| ~~紧急回切 Dify 开关~~ | 流量层方案与客户 IT 已对齐，写入 C1.16 |
| ~~LangFuse 数据合规上云~~ | self-hosted 现场部署，按 C1.11 推进 |
| ~~AI 数据标注员角色~~ | 二期 #37 启动前对齐，不阻塞一期 |

**当前唯一活跃 P0 阻塞**：PR #41 CI failure（阶段 0 A0.1）。

---

## 13. 关联资源

- **ADR 0016** · M3 范围重定义（工程联调闭环，非 Shadow 双跑）
- **ADR 0001 D9** · 原 M3 阶段定义（被 ADR 0016 修订）
- **ADR 0008 / 0013 / 0014** · ticker / 动态 prompt / LangFuse 后端
- **`docs/m2-real-llm-final-report.md`** · M2 92.5% pass rate baseline
- **`docs/SHADOW_COMPARE_GUIDE.md`** · Shadow 工具（M4 使用）
- **GitHub Epic** · #33（客户验证）/ #34（M3 v2）/ #35-#37（二期）

---

## 14. 下一步行动

讨论本路线图后请明确：

1. **认领**：每个任务 ID 旁 Owner 列若不准，团队 review 时改
2. **排期**：阶段 1 五条子线建议从同一天起跑；估时若不准，团队对齐后改
3. **review 节奏**：建议每周一同步会，按本文档表格逐条过状态

立即可启动：**A0.1 PR #41 CI failure 修绿**（不需要等讨论结果）。
