# ADR 0019 · 故障升级阈值（P0/P1/P2 量化判定）

- 状态：已采纳（阈值表与 alerts.py 逐条一致；**三项护栏存在实现偏离**，见对应小节）
- 日期：2026-05-12
- 起源：on-call-runbook §3 曾误引 ADR 0017（0017 是退出门阈值）；F4 灰度上线前补正
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #143）
- 作者：图灵科技 + Tony

## 上下文

[ADR 0017](./0017-m4-canary-quantitative-exit-gate.md) 定义的是 M4 **退出门**（"已经稳定，可宣告完成"）；本 ADR 定义**故障升级**（"正在出问题，多快介入"）。两组阈值方向相反且刻意拉开：例如 5xx 率 < 0.1% 才算稳定可下 Dify，但 ≥ 1% 持续 5 分钟才算 P0——中间是"亚健康可观察"区间，不打扰 on-call。`app/observability/alerts.py` 先于本 ADR 写入阈值形成"代码先行、ADR 缺位"，本 ADR 是事后形式化（技术债已偿付）。

## 决策

### 1. 自动机器告警（`app/observability/alerts.py` —— 核查确认 THRESHOLDS 与本表**逐条一致** ✅）

| name | severity | 阈值 | 持续 | 触发动作 | 测量现状 |
|---|---|---|---|---|---|
| `http_5xx_spike` | P0 | 5xx 率 ≥ 1% | 5 分钟 | 立即介入 + 评估回切 | ✅ |
| `cascade_fail_high` | P1 | fallback{cascade_fail} 率 ≥ 5% | 10 分钟 | 15 分钟介入 | ⚠️ 分母是 `node_total`（节点执行数），本 ADR 未定义分母、0017 写"总请求数"——两 ADR 同名指标口径不一致且代码取了最宽的一种，裁决 [#157](https://github.com/GZTL-AI/aigc-langgraph/issues/157) |
| `llm_failure_high` | P1 | llm_total{status≠ok} 率 ≥ 10% | 5 分钟 | 15 分钟介入 | ✅ |
| `non_canary_traffic` | P0 | is_canary=false 计数 ≥ 1 | 即时 | 立即回切 Webhook | ⚠️ 见"实现偏离" |
| `p95_latency_degraded` | P1 | P95 端到端 ≥ 12600ms（4200 × 3，`M2_BASELINE_P95_MS` 可调） | 10 分钟 | 15 分钟介入 | ⚠️ 直方图实际只装节点级耗时（端到端埋点未接线），用节点分布比端到端阈值**几乎不可能触发，告警形同虚设**——裁决 [#157](https://github.com/GZTL-AI/aigc-langgraph/issues/157) |

⚠️ **baseline 注记**：4200ms 为 Qwen + mock 口径，已随 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 失效；DeepSeek 真后端重测前 12600ms 仅为占位（本 ADR 原"后续行动"第 3 条，仍未执行）。

### 2. 人工升级判定（runbook 侧，与 `docs/on-call-runbook.md` §3 对应 ✅）

- **P0 · 5 分钟介入**：Java 后端不可达 ≥ 3 分钟（`/ready` 探测持续 fail）；进程崩溃 systemd restart 失败 ≥ 2 次；业务方明确反馈"系统完全不工作"。
- **P1 · 15 分钟介入**：P95 ≥ baseline × 3 持续 10 分钟；HITL 单会话挂起 ≥ 30 分钟；LangFuse 不可达 ≥ 10 分钟（监控盲区）。
- **P2 · 24 小时响应**：单条严重错例（标的错/参数错/意图大类错）；指标偶发越线未达持续阈值。多条同类错例 → 系统性问题升 P1。

### 3. 阈值取值理由（保留原论证，一处重写）

- 5xx 1%/5min 与退出门 0.1% 拉开十倍：故障升级关心突发，退出门关心稳态。
- cascade 5%/10min = P1 非 P0：fallback 给用户友好回复，非服务崩溃。
- **LLM 失败 ≥ 10%/5min（论证前提按 [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) 重写）**：LLM 现为**单一外部依赖 DeepSeek API**（5 个文本工厂同一 endpoint），失败冲高通常是上游故障；10% 是 retry × 2 后仍不通的水位。⚠️ 若未来启用 VL 图片链路（需单独接 Qwen base），将引入**第二个 vendor 依赖**，"单一依赖"论证与本条阈值需重估。
- non_canary ≥ 1 即时 P0：切流白名单外任何流量 = 企微 Webhook 配错，单条泄漏 1 秒内即可造成损失。
- P95 × 3/10min = P1：慢但未崩，10 分钟窗口区分抖动与卡死。
- HITL 30min = P1：金融业务方一般 10 分钟内响应明确提问，30 分钟未回大概率是系统问题。
- 单条错例 = P2：不阻塞其他流量；升 P1 会让 on-call 被告警淹没。

### 4. 与 ADR 0017 的关系（不变）

| 维度 | ADR 0017（退出门） | 本 ADR（故障升级） |
|---|---|---|
| 问题域 | 金丝雀**结束**判定 | 金丝雀**期间**定级 |
| 阈值方向 | 越好越绿（< 0.1%） | 越糟越红（≥ 1%） |
| 时间窗口 | 7 天累积 | 5-10 分钟滚动 |
| 决策权 | Tony + 业务方负责人 | on-call（P0/P1）/ 周报（P2） |

### 5. 阈值变更程序（补第 5 步）

1. 改 `app/observability/alerts.py:THRESHOLDS`
2. 改本 ADR §1/§2
3. 改 `docs/on-call-runbook.md` §3
4. 改 `docs/m3-f4.0-oncall-drill.md` Scene 2（文本叙述，人工修订，不在自动 lint 范围）
5. **（新增）核对 runbook §3 P0 行是否含 `non_canary_traffic`**——见下方偏离；lint 目前豁免该项，人工必查

CI lint ✅：`scripts/check_alert_threshold_consistency.py`（PR #106，25 测试 + CI step，本次核查实跑"三处阈值全部对齐"）。

## 实现偏离（裁决见 [#157](https://github.com/GZTL-AI/aigc-langgraph/issues/157)）

| 偏离 | 现状 |
|---|---|
| **`non_canary_traffic`(P0) 不在 runbook 定级表** | runbook §3 P0 行只列 5xx/Java 后端/进程崩溃/业务方反馈；且 lint **主动豁免**该项——CI 永远发现不了，值班照 runbook 定级会漏掉这条 P0 |
| **runbook §5 声称的 canary_status 护栏不存在** | runbook 写"`canary_status.py` 检测 `CANARY_ROOM_IDS=ALL` + `dry_run_intercept > 0` 时 P0 告警"；脚本无 `dry_run_intercept` 字样，`ALL` 模式反而直接 `is_breach=False`——**虚假安全护栏声明**，F4.1 shadow 期误下单风险无实际拦截 |
| **`p95_latency_degraded` 数据源失真** | 见 §1 表注：端到端埋点未接线，节点级分布对 12600ms 阈值形同虚设（与 [ADR 0017](./0017-m4-canary-quantitative-exit-gate.md) P95 项同根因） |

## 替代方案（保留）

合并进 0017（语义对立，reject）/ 只维护 alerts.py + runbook 不写 ADR（不够权威，reject）/ 更严阈值（告警疲劳）/ 更松阈值（信任崩塌）。

## 后果（现状口径）

- alerts.py + runbook + drill SOP 有共同 ADR 锚点；E3.6 sign-off 时可拿本 ADR 解释回切标准 ✅
- 后续行动状态更新：alerts.py 注释引用本 ADR **已完成**（原文标 FUTURE，实测 `alerts.py:4,19-27` 已含）；runbook 引用修正范围订正为 **§3 / §4 / 文末"关联资源"**（原文写 §9 是节号错误——§9 是变更记录表，本无 ADR 引用）；baseline 重测（DeepSeek 口径）仍未执行。

## 关联

- [ADR 0017](./0017-m4-canary-quantitative-exit-gate.md) · 退出门（互补）/ [ADR 0020](./0020-unify-all-llm-on-deepseek-v4-pro.md) · LLM 依赖与 baseline
- `app/observability/alerts.py` · 阈值代码 / `docs/on-call-runbook.md` §3-§5 / `docs/m3-f4.0-oncall-drill.md` / `scripts/rollback_canary.sh`
