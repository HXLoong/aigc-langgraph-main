# ADR 0019 · 故障升级阈值（P0/P1/P2 量化判定）

- 状态：已采纳
- 日期：2026-05-12
- 起源：on-call-runbook §3 引用 ADR 0017 但 0017 实为退出门阈值；F4 灰度上线前补正
- 作者：图灵科技 + Tony

## 上下文

`docs/on-call-runbook.md` §3「严重等级」声称"对齐 ADR 0017 量化指标"，但 ADR 0017 实际定义的是 **M4 退出门**阈值（金丝雀什么时候算稳定可下 Dify），是上线后 7 天稳定期的**结束**判定。

而 on-call-runbook §3 关心的是**故障升级**阈值：什么时候叫 P0、什么时候叫 P1、什么时候叫 P2，触发立即介入、15 分钟介入、24 小时响应三种响应速度。语义完全不同：
- ADR 0017 = "已经稳定了，可以宣告金丝雀完成"
- 本 ADR = "正在出问题，需要立即/尽快介入"

两组阈值数值也不一致。例如：
- ADR 0017：5xx 率 < 0.1% 才算稳定可下 Dify
- 本 ADR：5xx 率 ≥ 1% 持续 5 分钟才算 P0（即"严重到要回切"）

中间的 0.1% ~ 1% 区间，是"系统不完美但还能跑"——不阻碍金丝雀过门，也不触发回切。

再加上 `app/observability/alerts.py` 早已写入 4 条自动告警阈值（与 runbook §3 部分对齐但未文档化），形成"代码先行、ADR 缺位"的反规范状态。F4 灰度上线前必须补上正式 ADR，否则：
- on-call 值班时无法定级（"5xx 涨到 0.8% 算 P0 还是 P1？"）
- alerts.py 阈值改动无 ADR 锚点，git 历史里翻不到决策依据
- 业务方 sign-off 阶段无法回答"系统什么标准下你们才会主动回切"

## 决策

故障升级阈值分**两层**：自动机器告警（监控埋点即时判定）+ 人工升级判定（含主观/人工介入因素）。两层都属于本 ADR 范围。

### 1. 自动机器告警（代码侧 `app/observability/alerts.py`）

监控埋点 + delta 窗口计算自动触发。on-call 收到告警即可直接采取行动，无需人工判定。

| name | severity | 阈值 | 持续 | 触发动作 |
|---|---|---|---|---|
| `http_5xx_spike` | P0 | HTTP 5xx 率 ≥ 1% | 5 分钟 | 立即介入 + 评估回切 |
| `cascade_fail_high` | P1 | fallback{reason=cascade_fail} 率 ≥ 5% | 10 分钟 | 15 分钟介入 |
| `llm_failure_high` | P1 | llm_total{status≠ok} 率 ≥ 10% | 5 分钟 | 15 分钟介入 |
| `non_canary_traffic` | P0 | is_canary=false 计数 ≥ 1 | 即时（0 秒） | 立即回切 Webhook |
| `p95_latency_degraded` | P1 | P95 端到端延迟 ≥ 12600ms（M2 baseline 4200ms × 3） | 10 分钟 | 15 分钟介入 |

`non_canary_traffic` 是 G5.1 金丝雀切流期特有——任何非白名单 roomId 进入 LangGraph 都视为企微管理员误操作，必须立即截断。

`p95_latency_degraded` baseline 可通过 `M2_BASELINE_P95_MS` env 调整（PR #103）；M3 真后端测得新数据后由运维更新本表对应的 ms 值。

### 2. 人工升级判定（runbook 侧）

无法或不适合自动判定的情况，由 on-call 工程师按以下规则人工定级：

#### P0 · 5 分钟内介入

- Java 后端持续不可达 ≥ 3 分钟（`/ready` 探测 `java_backend=fail` 持续）
- LangGraph 应用进程崩溃无法自愈（systemd restart 失败 ≥ 2 次）
- 业务方在企微群明确反馈"系统完全不工作"

#### P1 · 15 分钟内介入

- P95 端到端延迟 ≥ M2 baseline × 3 持续 10 分钟（M2 baseline 由 #29 测得 ≈ 4.2s，因此 P1 阈值 ≈ 12.6s）
- HITL 单条会话挂起 ≥ 30 分钟无业务方回复（与 ticker 子图 + ADR 0006 配合）
- LangFuse 不可达 ≥ 10 分钟（监控盲区）

#### P2 · 24 小时内响应

- 业务方反馈单条"严重错例"（标的错 / 参数错 / 意图大类错；非主观"AI 不够聪明"）
- 监控指标偶发越线但未达持续阈值
- 客户业务方反馈"个别 case 不准"

### 3. 阈值取值理由

#### 为什么 5xx ≥ 1% 持续 5min = P0（与 0017 退出门 0.1% 拉开十倍）

退出门关心稳态，故障升级关心**突发**。瞬时 5xx 跳到 0.8% 又恢复并非紧急情况——5 分钟持续过 1% 才说明真的崩了。0.1%~1% 是"亚健康但可观察"区间，不打扰 on-call。

#### 为什么 Cascade fail ≥ 5% 持续 10min = P1（不是 P0）

Cascade fail 触发 fallback render 给用户友好回复，**不是服务崩溃**。即使持续，业务方仍能继续使用（只是错误率高）。15 分钟介入足够诊断 + 决定回切；不需要 5 分钟级响应。但 ≥ 5% 已经是 M2 baseline 7.5% 失败率中 cascade 子集的 1.5× 红线（M2 baseline cascade ≈ 3.3%），值得人工查。

#### 为什么 LLM 失败 ≥ 10% 持续 5min = P1

LLM 是单一外部依赖（Qwen 标准 / thinking / VL 同一 API），失败率冲高通常是上游故障。10% 是单次 retry × 2 后仍不通的水位——超过该值即使重试也救不回来。5 分钟持续而非 10 分钟，因为 LLM 故障比 cascade 故障扩散更快（每个新请求都受影响）。

#### 为什么 non_canary_traffic ≥ 1 即时触发 P0

F4.2-F4.5 灰度切流期，CANARY_ROOM_IDS 白名单严格定义谁能进 LangGraph。**任何**白名单外的群进入都意味着企微管理员配错了 Webhook → 业务方完全没准备就在用未验证的系统。即时回切（rollback_canary.sh）成本远低于一次客诉。

不等持续时间是因为：单条流量泄漏可能在 1 秒内造成业务方损失（错误下单建议），10 分钟才告警等于放任不管。

#### 为什么 P95 × 3 持续 10min = P1（不是 P0）

延迟 3× 还能正常返回（只是慢）。chat UX 退化但**未崩溃**，业务方仍可决定继续等还是放弃。10 分钟介入窗口允许 on-call 区分"短暂网络抖动"和"真的卡住"。

#### 为什么 HITL 挂起 ≥ 30min = P1（不是 P2）

HITL 卡片渲染到企微但没收到回复，2 个解释：
1. 用户离开了（与系统无关，P2）
2. 卡片没正确发送 / 业务方看到了但不知道怎么回复（系统问题，P1）

30 分钟阈值是经验值——金融业务方一般 10 分钟内会响应明确的提问；30 分钟还没回 = 大概率是系统问题。

#### 为什么严重错例是 P2 而非 P1

单条业务错例**不阻塞**生产流量。其他客户的请求照常处理，只是这一条出了问题。M2 baseline PASS 率 92.5% 意味着 7.5% 的请求会有问题——把单条错例升 P1 会让 on-call 每天被叫醒几十次，没人能坚持。日常错例进 24 小时窗口的周报周期更合理。

但**多条同类**错例 → 系统性问题，升 P1（runbook §5.2 cascade fail 路径覆盖）。

### 4. 与 ADR 0017 的关系

两份 ADR 共存，**互不替代**：

| 维度 | ADR 0017（退出门） | ADR 0019（本文 · 故障升级） |
|---|---|---|
| 问题域 | 金丝雀**结束**判定 | 金丝雀**期间**故障定级 |
| 阈值方向 | 越好越绿（< 0.1%） | 越糟越红（≥ 1%） |
| 触发动作 | 业务方 sign-off + Dify 下线 | on-call 介入 + 评估回切 |
| 时间窗口 | 7 天累积 | 5-10 分钟滚动窗口 |
| 决策权 | Tony + 业务方负责人 | on-call 工程师（P0/P1）/ 周报跟进（P2） |

### 5. 阈值变更程序

任何阈值改动必须：
1. 改 `app/observability/alerts.py:THRESHOLDS`（如适用）
2. 改本 ADR 第 1/2 节对应行
3. 改 `docs/on-call-runbook.md` §3 严重等级表
4. 改 `docs/m3-f4.0-oncall-drill.md` Scene 2 故障注入预期（如阈值影响演练）

四处不同步 = 上线事故。CI lint 已实现：`python scripts/check_alert_threshold_consistency.py`（PR #106），接入 `.github/workflows/ci.yml`，任一不一致 → CI fail。

## 替代方案

### 把阈值合并写进 ADR 0017

放弃：0017 是金丝雀**完成**阈值，本 ADR 是**故障**阈值，语义对立。混合写一份会让读者困惑何时引用哪段。

### 不写 ADR，仅维护 alerts.py + runbook

放弃：runbook §3 已经引用过 "ADR 0017"，证明 on-call 在脑子里需要一份正式可引用的决策文档。代码注释和 runbook §3 都不够"权威"——出 P0 时引用 ADR 比引用 README 更不容易被质疑。

### 更严的阈值（5xx 0.1% / cascade 1% / LLM 5%）

放弃：会让 on-call 每天接收大量 false-positive 告警，造成"告警疲劳"。一旦 on-call 开始忽略告警，真正的 P0 也会被淹没。M2 实测的 baseline 是设计阈值的起点。

### 更松的阈值（5xx 5% / cascade 10%）

放弃：金融客户容错低，5% 5xx = 每 20 条请求 1 条崩溃，业务方会立即失去信任。LangGraph 即使不如 Dify 也不能严重退化。

## 后果

### 正面

- alerts.py + runbook + drill SOP 三处阈值有共同的 ADR 锚点
- on-call 值班定级有正式依据可引用
- 业务方 sign-off 阶段（E3.6）可拿本 ADR 解释"我们什么标准下回切"

### 负面

- 阈值变更要 4 处同步（程序成本，但比"代码改了文档没跟上"好太多）
- M2 baseline 是 P95×3 等阈值的依据；M3 真后端 baseline 应更新时本 ADR 要 amendment
- runbook §3 +  alerts.py 已有阈值与本 ADR 完全对齐——本 ADR 是"事后形式化"而非"事前决策"，**这是技术债，本次偿付**

### 后续行动

- `docs/on-call-runbook.md` §3/§4/§9 引用从 "ADR 0017" 改为 "ADR 0019"（本 PR 同步）
- alerts.py 添加注释行引用本 ADR（**FUTURE**，下个 alerts 改动顺带）
- M3 真后端跑稳后用真实数据重测 baseline，必要时 amendment 本 ADR
- CI lint：检测 3 处阈值同步（alerts.py / ADR 0019 §1 / runbook §3）✅ PR #106
  · `scripts/check_alert_threshold_consistency.py`（25 个测试 + CI workflow step）
  · 第 4 处 m3-f4.0-oncall-drill.md Scene 2 演练阈值是文本叙述（"P95 ≥ baseline × 3"等），不在自动 lint 范围；人工修订即可

## 关联

- [ADR 0017](./0017-m4-canary-quantitative-exit-gate.md) · M4 退出门量化指标（互补 ADR，两者并列）
- [`app/observability/alerts.py`](../../app/observability/alerts.py) · 自动告警阈值代码定义
- [`docs/on-call-runbook.md`](../on-call-runbook.md) §3-§5 · 人工升级判定 + 故障 playbook
- [`docs/m3-f4.0-oncall-drill.md`](../m3-f4.0-oncall-drill.md) · F4.0 演练剧本
- [`scripts/rollback_canary.sh`](../../scripts/rollback_canary.sh) · P0 触发后的回切工具
