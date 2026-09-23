# ADR 0019 · 故障升级阈值（P0/P1/P2 量化判定）

- 状态：已采纳（阈值表与 alerts.py 逐条一致；三项护栏偏离已于 2026-08-27 修复）
- 日期：2026-05-12
- 起源：on-call-runbook §3 曾误引退出门阈值（现为 ADR 0030 D3）；灰度上线前补正
- 修订：2026-09-22 互补关系改指向 [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3；2026-08-27 深度改写为现状口径（对照代码核查）
- 作者：图灵科技 + Tony

## 上下文

[ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3 的上线观察层定义的是**退出门**（"已经稳定"）；本 ADR 定义**故障升级**（"正在出问题，多快介入"）。两组阈值方向相反且刻意拉开：例如 5xx 率 < 0.1% 才算稳定可下 Dify，但 ≥ 1% 持续 5 分钟才算 P0——中间是"亚健康可观察"区间，不打扰 on-call。`app/observability/alerts.py` 先于本 ADR 写入阈值形成"代码先行、ADR 缺位"，本 ADR 是事后形式化（技术债已偿付）。

## 决策

### 1. 自动机器告警（`app/observability/alerts.py` —— 核查确认 THRESHOLDS 与本表**逐条一致** ✅）

| name | severity | 阈值 | 持续 | 触发动作 | 测量现状 |
|---|---|---|---|---|---|
| `http_5xx_spike` | P0 | 5xx 率 ≥ 1% | 5 分钟 | 立即介入 + 评估回切 | ✅ |
| `cascade_fail_high` | P1 | fallback{cascade_fail} 率 ≥ 5% | 10 分钟 | 15 分钟介入 | ✅ 分母 = `http_total`（总请求数，2026-08-27 修复，与 0030 D3 口径统一） |
| `llm_failure_high` | P1 | llm_total{status≠ok} 率 ≥ 10% | 5 分钟 | 15 分钟介入 | ✅ |
| `non_canary_traffic` | P0 | is_canary=false 计数 ≥ 1 | 即时 | 立即回切 Webhook | ✅ runbook §3 已补条目，lint 校验 5/5/5 |
| `p95_latency_degraded` | P1 | P95 端到端 ≥ 25662ms（8554 × 3，`M2_BASELINE_P95_MS` 可调） | 10 分钟 | 15 分钟介入 | ✅ 端到端埋点已接线且 P95 剔除节点级样本；2026-09-24 已按 DeepSeek dry-run 参考值回填，生产需覆盖 |

**baseline 注记（2026-09-24）**：旧 Qwen + mock 的 4200ms 占位已替换为 DeepSeek-V4-pro 本地 dry-run 实测 P95 **8554ms**。冻结版本、显式 categories、并发 1、MySQL 持久化，实际 417 次 HTTP；5xx 0/417，cascade 原始计数 41/417（9.83%，包含明确拒绝）。写入被拦截，业务断言 2/391 PASS；这不是交易成功或生产 7 天观察通过。详细报告在 `tmp/goal-issues/current-model-dryrun-baseline.json` 及同目录报告。生产启用前须用同部署拓扑测量并通过 `M2_BASELINE_P95_MS` 覆盖，不能直接照搬本地参考值。

### 2. 人工升级判定（runbook 侧，与 `docs/on-call-runbook.md` §3 对应 ✅）

- **P0 · 5 分钟介入**：Java 后端不可达 ≥ 3 分钟（`/ready` 探测持续 fail）；进程崩溃 systemd restart 失败 ≥ 2 次；业务方明确反馈"系统完全不工作"。
- **P1 · 15 分钟介入**：P95 ≥ baseline × 3 持续 10 分钟；HITL 单会话挂起 ≥ 30 分钟；LangFuse 不可达 ≥ 10 分钟（监控盲区）。
- **P2 · 24 小时响应**：单条严重错例（标的错/参数错/意图大类错）；指标偶发越线未达持续阈值。多条同类错例 → 系统性问题升 P1。

### 3. 阈值取值理由（保留原论证，一处重写）

- 5xx 1%/5min 与退出门 0.1% 拉开十倍：故障升级关心突发，退出门关心稳态。
- cascade 5%/10min = P1 非 P0：fallback 给用户友好回复，非服务崩溃。
- **LLM 失败 ≥ 10%/5min（论证前提按 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 重写）**：LLM 现为**单一外部依赖 DeepSeek API**（5 个文本工厂同一 endpoint），失败冲高通常是上游故障；10% 是 retry × 2 后仍不通的水位。⚠️ **2026-09-22 复核：VL 图片链路已接线**（`app/subgraphs/swap/multimodal.py`，swap 图 image / excel 分支；`QWEN_MODEL_VL` 走独立视觉模型）——第二个 vendor 依赖已成事实，"单一依赖"论证不再成立；`llm_failure_high` 按 `model` label 拆分阈值列为待办，重估前本条阈值继续沿用。
- non_canary ≥ 1 即时 P0：切流白名单外任何流量 = 企微 Webhook 配错，单条泄漏 1 秒内即可造成损失。
- P95 × 3/10min = P1：慢但未崩，10 分钟窗口区分抖动与卡死。
- HITL 30min = P1：金融业务方一般 10 分钟内响应明确提问，30 分钟未回大概率是系统问题。
- 单条错例 = P2：不阻塞其他流量；升 P1 会让 on-call 被告警淹没。

### 4. 与 ADR 0030 D3 上线观察层的关系

| 维度 | ADR 0030 D3（退出门） | 本 ADR（故障升级） |
|---|---|---|
| 问题域 | 灰度**结束**判定 | 灰度**期间**定级 |
| 阈值方向 | 越好越绿（< 0.1%） | 越糟越红（≥ 1%） |
| 时间窗口 | 7 天累积 | 5-10 分钟滚动 |
| 决策权 | 项目负责人 + 业务方负责人 | on-call（P0/P1）/ 周报（P2） |

### 5. 阈值变更程序（补第 5 步）

1. 改 `app/observability/alerts.py:THRESHOLDS`
2. 改本 ADR §1/§2
3. 改 `docs/on-call-runbook.md` §3
4. 改 `docs/on-call-runbook.md` §8 回切演练计划中引用阈值的场景（文本叙述，人工修订，不在自动 lint 范围）
5. **（新增）runbook §3 P0 行的 `non_canary_traffic` 条目已入 lint 校验范围**（豁免已解除），随第 3 步一并同步

CI lint ✅：`scripts/check_alert_threshold_consistency.py`（25 测试 + CI fast job）。

## 实现偏离（已全部修复，2026-08-27 裁决落地）

| 偏离 | 现状 |
|---|---|
| ~~`non_canary_traffic`(P0) 不在 runbook 定级表~~ | ✅ 已修复：runbook §3 P0 行已补该条，lint 豁免解除（现校验 5/5/5） |
| ~~runbook §5 声称的 canary_status 护栏不存在~~ | ✅ 已实现：canary_status 解析 `otc_agent_dry_run_intercept_total`，ALL 模式 + 拦截>0 → is_breach（P0），声明成真 |
| ~~`p95_latency_degraded` 数据源失真~~ | ✅ 已修复：端到端埋点接线 + 节点样本剔除（同 §1 表注） |

## 替代方案（保留）

合并进 0017（语义对立，reject）/ 只维护 alerts.py + runbook 不写 ADR（不够权威，reject）/ 更严阈值（告警疲劳）/ 更松阈值（信任崩塌）。

## 后果（现状口径）

- alerts.py + runbook + drill SOP 有共同 ADR 锚点；业务方培训时可拿本 ADR 解释回切标准 ✅
- 后续行动状态更新：alerts.py 注释引用本 ADR **已完成**（原文标 FUTURE，实测 `alerts.py:4,19-27` 已含）；runbook 引用修正范围订正为 **§3 / §4 / 文末"关联资源"**（原文写 §9 是节号错误——§9 是变更记录表，本无 ADR 引用）；DeepSeek 本地 dry-run 参考基线已于 2026-09-24 回填，生产同拓扑测量与 7 天观察仍待执行。

## 关联

- [ADR 0030](./0030-goal-restatement-native-langgraph-dataset-eval-harness.md) D3 · 上线观察退出门（互补）/ [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · LLM 依赖与 baseline
- `app/observability/alerts.py` · 阈值代码 / `docs/on-call-runbook.md` §3-§5、§8 / `scripts/rollback_canary.sh`
