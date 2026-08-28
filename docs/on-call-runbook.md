# otc-agent On-Call Runbook · 值班手册（草稿）

> **版本**：v0.1 草稿（2026-05-12）
> **状态**：草稿——M3 阶段 1 C1.16 产出；**真实回切演练（F4.0）**在阶段 4 完成后基于实测更新到 v1.0
> **适用范围**：客户现场生产环境的 LangGraph + 后台依赖（Java 后端 / DeepSeek-v4-pro / LangFuse / MySQL）
> **维护**：图灵科技工程团队 + 客户企微管理员

---

## 1. 文档目的

让值班工程师能在**5 分钟内**做出"故障定级 → 回切决策 → 通知动作"。

本手册不替代代码注释和 ADR——它只关心**生产环境出问题时怎么办**，不解释为什么这么设计。

---

## 2. 角色与联系方式

> **首次部署时由 Tony 填写真实联系信息，每季度 review 一次。**

| 角色 | 职责 | 联系方式 |
|---|---|---|
| **图灵科技 on-call 值班工程师** | 第一响应（监控告警 → 诊断 → 决策）；非工作时间随叫随到 | 待填：手机 / 企微 |
| **图灵科技工程负责人 #25** | 升级响应（P0/P1 故障 30 分钟内介入） | 待填：手机 / 企微 |
| **项目负责人 Tony** | 业务方沟通 + 客户协调 + 回切授权 | 待填：手机 / 企微 |
| **客户企微管理员** | 执行紧急回切（改 Webhook 地址） | 待填：企微 ID / 备用电话 |
| **客户 IT 联系人** | LangFuse / 服务器 / 网络层故障 | 待填：手机 / 邮箱 |
| **客户业务方 sign-off 人** | 业务级判定（"严重错例"标注） | 待填：邮箱 |

**联系优先级**：值班工程师 → 工程负责人 → Tony → 客户企微管理员/IT。**不绕级直接找客户 IT**——避免重复打扰。

---

## 3. 严重等级（Severity）

对齐 [ADR 0019](./adr/0019-incident-severity-thresholds.md) 量化指标。值班工程师按下表定级，决定响应速度。

| 级别 | 判定标准（满足任一） | 响应时间 | 处置动作 |
|---|---|---|---|
| **P0** | · HTTP 5xx 率 ≥ 1% 持续 5 分钟<br>· 非金丝雀流量泄漏 ≥ 1 条（即时，non_canary_traffic → 立即回切）<br>· Java 后端不可达持续 3 分钟<br>· LangGraph 应用进程崩溃无法自愈<br>· 业务方反馈"系统完全不工作" | **5 分钟内介入** | 立即执行紧急回滚（§7）+ 通知工程负责人 + Tony |
| **P1** | · Cascade fail 率 ≥ 5% 持续 10 分钟<br>· LLM 失败率 ≥ 10% 持续 5 分钟<br>· P95 延迟 ≥ M2 baseline × 3 持续 10 分钟<br>· HITL 单条会话挂起 ≥ 30 分钟无恢复 | **15 分钟内介入** | 诊断根因 + 评估是否需回滚；通知工程负责人 |
| **P2** | · 单条业务错例（"严重错例"标注）<br>· 监控指标偶发越线但未持续<br>· 客户业务方反馈"个别 case 不准" | 24 小时内响应 | 记录 + 周报跟进；通常进入下一迭代修补 |

> **不要为 P2 触发回滚**——回滚的恢复成本高于个别 case 错误。

---

## 4. 监控告警来源

| 来源 | 监控对象 | 阈值（对齐 [ADR 0019](./adr/0019-incident-severity-thresholds.md)） |
|---|---|---|
| LangFuse trace 仪表盘 | 5xx 率 / cascade fail 率 / P95 延迟 / fallback render 触发率 | 见 §3 P0/P1 判定标准 |
| 业务监控埋点（C1.5 产出） | 每意图 PASS 率 / 节点错误 / HITL 触发率 | 见 §3 P0/P1 判定标准 |
| Java 后端健康检查 | `/health` `/ready`（C1.9 产出，依赖 4 个上游） | 上游任一不通 → P1；持续 3 分钟 → P0 |
| MySQL Checkpointer | 连接池打满 / write timeout | 持续 1 分钟 → P1 |
| 业务方反馈 | 企微群 @值班工程师 或 sign-off 人邮件 | 单条 P2；多条同类 P1 |

**告警接收点**：图灵科技团队企微告警群（待 Tony 创建并拉群）。客户业务方不直接接收技术告警。

---

## 5. 常见故障处置 Playbook

### 5.1 LangGraph 5xx 崩溃

| 步骤 | 动作 |
|---|---|
| 1 | LangFuse trace 仪表盘看最近 5 分钟 5xx 占比；若 ≥ 1% 持续 → 升 P0 |
| 2 | 看错误堆栈聚类：是 LLM 超时？Java 后端 5xx？MySQL 写失败？ |
| 3 | 若是 LLM 超时：检查 DeepSeek API 状态页（公网） + 网络出口；可临时把节点 timeout 拉长（环境变量）但不长久 |
| 4 | 若是 Java 后端 5xx：联系客户 IT 排查后端服务状态 |
| 5 | 若是 MySQL 写失败：检查 checkpoint 表锁 + 磁盘空间 + 连接池 |
| 6 | 5 分钟内未根因诊断 → 执行紧急回滚（§7） |
| 7 | 事后写故障报告，进入下周回顾 |

### 5.2 Cascade Fail 持续触发

**定义**：节点抛异常 → `safe_node` 捕获 → 写 `state['error']` → 下游路由到 fallback render，用户看到"我没完全理解你的意思..."

| 步骤 | 动作 |
|---|---|
| 1 | LangFuse 看 fallback render 节点触发率；≥ 5% 持续 10 分钟 → 升 P1 |
| 2 | 看 trace 中是哪个节点写入了 error；按 `suspected_node` 字段归类 |
| 3 | 多数同节点 → 该节点 prompt / Pydantic 模型 / 后端调用有共性 bug |
| 4 | 多数同 prompt 类型（如多个 extract 节点都炸）→ LLM 后端有问题（模型升级 / API 接口变更） |
| 5 | 不同节点散布 → 系统性问题（如 MySQL 写延迟拖慢 timeout） |
| 6 | 若来源明确且能热修：用 LangFuse Prompt 在线版本切换回上版本（ADR 0014）|
| 7 | 若来源不明 + 持续 30 分钟未改善 → 执行紧急回滚（§7） |

### 5.3 HITL 长时间未恢复

**定义**：ticker 子图触发 HITL（多命中分差 < 10）后，用户超过 30 分钟未回复消歧选择。

| 步骤 | 动作 |
|---|---|
| 1 | 看具体哪个 conversation_id 挂起；若是单条会话——P2，不影响整体 |
| 2 | 若多条会话同时挂起 → HITL 消歧卡片可能没正确发送到企微（卡片渲染问题）→ 升 P1 |
| 3 | 看 LangFuse trace 中 render 节点输出是否包含 HITL 候选列表 |
| 4 | 若 render 输出正确但企微未显示 → 客户 IT 排查企微机器人消息推送 |
| 5 | 若 render 输出错误 → 工程团队补丁 |

### 5.4 Java 后端不可达

| 步骤 | 动作 |
|---|---|
| 1 | 应用日志会有"OTC backend timeout"批量错误 |
| 2 | curl `/admin-api/health`（如有）或某个低频读 endpoint 试连通性 |
| 3 | 不通 → 联系客户 IT 排查 Java 服务状态、网络、端口 |
| 4 | 持续 3 分钟不通 → 升 P0 + 紧急回滚（§7） |
| 5 | 注：tools 层有不可达降级（D2.3）会返回友好 fallback，但不能掩盖业务影响 |

### 5.5 LangFuse 不可达

| 步骤 | 动作 |
|---|---|
| 1 | 监控告警停止上报（监控空白也是 P1 信号） |
| 2 | trace 写失败不影响主链路（应用容错），但**故障诊断能力丧失**——必须尽快恢复 |
| 3 | 客户 IT 排查 LangFuse self-hosted 容器状态 |
| 4 | LangFuse 恢复后，期间的 trace 数据**不可补录**，需在故障报告中明确"诊断盲区时段" |

### 5.6 MySQL Checkpointer 失败

| 步骤 | 动作 |
|---|---|
| 1 | 应用日志有"AIOMySQLSaver write failed"或连接池超时 |
| 2 | 不立即崩溃，但多轮对话会失去历史记忆——业务方看到"AI 不记得之前说过什么" |
| 3 | 客户 IT 排查 MySQL 状态、连接数、磁盘 |
| 4 | 短期可重启应用清理连接池；长期需扩 MySQL 资源 |

### 5.7 DRY_RUN_BACKEND 误配（F4.1 ↔ F4.2 切换时）

**误配场景 A**：F4.2 切流后忘记把 `DRY_RUN_BACKEND` 改回 false → 用户下单全部被拦截 → 业务方反馈"下单没反应/订单查不到"

| 步骤 | 动作 |
|---|---|
| 1 | 现象判定：`curl /metrics | grep dry_run_intercept` 看是否在涨；业务方反馈"下单按了但 GOATS 没记录" |
| 2 | 立即查 `.env::DRY_RUN_BACKEND`：F4.2+ 必须 `false`（F4.1 shadow 期才 `true`）|
| 3 | 修 .env 后**必须重启** otc-agent 让 settings 重新加载（lru_cache 单例）|
| 4 | 验证：跑一条业务 case，看 GOATS 是否真创建订单；`/metrics` 上 `dry_run_intercept` 计数不应再涨 |

**误配场景 B**：F4.1 shadow 期忘开 `DRY_RUN_BACKEND=true` → LangGraph 真下单 → **严重事故** + 业务方信任损失

| 步骤 | 动作 |
|---|---|
| 1 | 立即通知 Tony + 业务方负责人 |
| 2 | 立即停 shadow 双跑（停 LangGraph 实例 / 把 Webhook 切回 Dify）|
| 3 | 拉取 LangGraph trace + GOATS 订单日志，列出"误下单"清单 |
| 4 | 业务方协调撤单（如还能撤）+ 客户书面致歉 |
| 5 | 事后必须 postmortem：为什么 deploy 时 step2 advisory 没拦住 |

**预防机制**（已实现）：
- `scripts/deploy-customer.sh` step2 加 advisory（待落地，#113）
- `scripts/canary_status.py` 检测 `CANARY_ROOM_IDS=ALL` + `dry_run_intercept > 0` 时 P0 即时告警
- `docs/archive/m3/m3-shadow-compare-dry-run-design.md` §3 安全护栏

---

## 6. 不要做的事

| 禁忌 | 原因 |
|---|---|
| 不要直接 SSH 改生产配置 | 改了无审计；应通过部署流程 + git 记录 |
| 不要在生产用 `dangerously-skip-permissions` 跑命令 | 任何破坏性操作必须有审计 |
| 不要为单条 P2 触发回滚 | 回滚成本 > 个别 case 损失 |
| 不要绕过工程负责人直接联系客户 IT | 同一故障多人介入会乱套 |
| 不要在告警群外通报 P0 | 业务方看到技术告警会恐慌；P0 走 Tony → 业务方话术统一 |
| 不要在故障未根因时 push hotfix | 可能引入新问题；先回滚再修 |

---

## 7. 紧急回滚（Emergency Rollback）操作

**目标**：5 分钟内把企微群消息流量切回 Dify。

**前提**：阶段 5 G5.2a 之前（即"Dify 半下线"前）回切能力一直保留；阶段 5 G5.2b 之后回切不可用，详见路线图阶段 5。

### 7.1 决策权

| 触发场景 | 谁有权决策 |
|---|---|
| P0 自动满足条件（5xx ≥ 1% 持续 5 分钟等） | 值班工程师直接执行（不等通知） |
| P1 风险评估后决定回切 | 工程负责人 + Tony 双确认 |
| 业务方主动要求回切 | Tony 拍板 |

### 7.2 执行步骤（企微管理员侧）

1. **企微管理员登录** 企微管理后台
2. **进入** 应用管理 → 自建应用 → 找到 otc-agent 机器人
3. **修改 Webhook URL**：
   - 当前：`https://<langgraph-host>/v1/workflows/run`（LangGraph endpoint）
   - 改为：`https://<dify-host>/v1/workflows/run`（Dify endpoint，**部署前由 Tony 提供完整 URL 填入本手册附录 A**）
4. **保存配置**
5. **验证**：5 分钟内在测试群发一条已知 case，确认回复来自 Dify（可对比文案风格判断；Dify 回复通常更格式化）

### 7.3 通知动作（值班工程师侧，并行执行）

| 时间 | 动作 |
|---|---|
| T+0 | 告警群通报"已触发紧急回滚，原因：..." |
| T+1 分钟 | 通知工程负责人 + Tony（电话或企微） |
| T+5 分钟 | 验证 Dify 已接管流量（看 Dify 侧日志） |
| T+15 分钟 | Tony 通知业务方 sign-off 人（话术：系统切换至备用流程，预计 X 时间内恢复） |
| T+1 小时 | 起草初步故障报告 |
| T+24 小时 | 完整故障报告 + 根因 + 修复计划交付 |

### 7.4 回归（Rollforward）流程

修复完成后切回 LangGraph：

1. 在测试群（非生产）先切回 LangGraph Webhook，跑 ≥ 30 条 smoke
2. 全绿 → 工程负责人 + Tony 双确认
3. 企微管理员把生产群的 Webhook 切回 LangGraph
4. 告警群通报"已切回 LangGraph"
5. **持续观察 24 小时**——确认指标恢复正常

> **不要在故障当天回切**——给 LangGraph 至少 12 小时观察期，避免反复横跳让业务方失去信心。

---

## 8. F4.0 演练计划（阶段 4 启动前）

> 详见路线图 F4.0 任务卡。

| 演练点 | 验证内容 | 通过标准 |
|---|---|---|
| 企微管理员能在 5 分钟内完成 Webhook 切换 | 实测从决策到生效全程时间 | ≤ 5 分钟 |
| 切换后流量真的到 Dify | Dify 侧日志看到新请求 | ✅ |
| 工程团队通知链路通畅 | 告警群 → 负责人 → Tony 的通知到达延迟 | ≤ 3 分钟 |
| 回归流程可执行 | 演练后能干净切回 LangGraph | ✅ |
| 演练发现的失败模式 | 补充进本手册 §5 / §7 | 形成 v1.0 正式版 |

演练负责人：Tony + 企微管理员；图灵科技值班工程师全程旁观+记录。

---

## 9. 变更记录

| 版本 | 日期 | 修改人 | 变更摘要 |
|---|---|---|---|
| v0.1 草稿 | 2026-05-12 | 图灵科技团队 | 初版草稿（C1.16 产出），含 5 类故障 playbook + 紧急回滚步骤 + 演练计划 |
| v1.0 | 待定（F4.0 演练后） | 图灵科技团队 | 基于演练实测更新 |

---

## 附录 A · 真实 URL / 联系人填写区（部署前由 Tony 填）

> **本附录是生产部署前必填的具体信息**，留空时本手册无法实际执行。

| 项目 | 真实值 |
|---|---|
| LangGraph 生产 Webhook URL | 待填 |
| Dify 生产 Webhook URL | 待填 |
| 企微管理后台访问地址 | 待填 |
| LangFuse 管理后台访问地址 | 待填 |
| Java 后端基础 URL | 待填 |
| 监控告警群企微群号 | 待填 |
| 客户企微管理员姓名 + 联系方式 | 待填 |
| 客户 IT 联系人 + 备用电话 | 待填 |
| 业务方 sign-off 邮箱 | 待填 |

---

## 关联资源

- **[ADR 0019](./adr/0019-incident-severity-thresholds.md)** · 故障升级阈值（本手册 §3-§4 严重等级 + alerts.py 阈值的依据）
- **[ADR 0017](./adr/0017-m4-canary-quantitative-exit-gate.md)** · M4 金丝雀退出门量化指标（互补：金丝雀结束判定，不是故障升级）
- **CONTEXT.md** · "紧急回滚"术语定义（本手册 §7 的语义来源）
- **`docs/m3-m4-roadmap.md`** · C1.16（本草稿任务卡）/ F4.0（演练任务卡）
- **`docs/SHADOW_COMPARE_GUIDE.md`** · Shadow 双跑工具（F4.1，与本手册无直接依赖）
- **`docs/TROUBLESHOOTING.md`** · 开发期通用故障排查（与生产 on-call 不同语境）

## checkpoint 表清理(客户现场例行运维,2026-08 架构体检改进 B)

LangGraph checkpoint 三表(checkpoints / checkpoint_blobs / checkpoint_writes)只增不减,
长期运行持续膨胀。按「线程最近一次 checkpoint 时间」清理,保留活跃会话完整历史:

```bash
# 每日巡检(dry-run,只报数)
python scripts/cleanup_checkpoints.py --days 30

# 确认数字合理后真删
python scripts/cleanup_checkpoints.py --days 30 --execute
```

- 建议 cron 每日低峰执行 `--execute`;保留天数按客户会话时效要求调整(默认 30 天)
- 判据是 checkpoint JSON 的 `$.ts`(线程最新一条早于 N 天前即整线程删除)
- 删除对业务无感:被删线程等价于"新会话从零开始",不影响在保留期内的多轮上下文
- 交付包必含此脚本;首次上线一个月后检查表大小确认 cron 生效
