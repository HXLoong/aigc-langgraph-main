# 生产故障 SOP · 根因诊断 + 修复手册

> **版本**：v1.0（2026-05-12）
> **适用范围**：客户现场生产环境的 LangGraph 应用运行时故障
> **关联**：
> - `docs/operations/on-call-runbook.md`（值班手册，**决策导向**）
> - `docs/development/troubleshooting.md`（开发期 Q&A，**调试导向**）
> - 本文档（生产 SOP，**根因诊断 + 修复路径导向**）

本文档与 on-call runbook 互补：
- **Runbook** 回答"出问题怎么响应"（定级 / 通知 / 回滚决策）
- **本文档** 回答"为什么会出这个问题、具体怎么修"

按故障类型组织，每个故障章节固定 6 部分：
1. **识别信号** · 监控/日志/业务表现的对应特征
2. **可能根因** · 5-8 个常见原因清单（按概率排序）
3. **诊断步骤** · 确认根因的命令/查询
4. **修复方案** · 按根因分支的修复路径
5. **禁忌** · 千万不要做的事
6. **修复后验证** · 确认问题真的解决了

---

## 1. Cascade Fail 持续触发

### 1.1 识别信号

- LangFuse 仪表盘：fallback render 节点触发率 ≥ 5% 持续 10 分钟（对齐 ADR 0019 P1 阈值）
- 应用日志：`safe_node` 装饰器批量记录 `state['error']` 写入
- 业务方反馈："AI 总说听不懂"、"对话经常被打断"
- 严重程度：P1（参考 on-call runbook §3）

### 1.2 可能根因（按概率排序）

| 概率 | 根因 | 信号 |
|---|---|---|
| 高 | LLM 调用失败后 Pydantic 解析失败 | trace 里 LLM 节点抛 `ValidationError` |
| 高 | 后端 5xx 引发 cascade（节点收到非法响应）| trace 里 OTC client 节点抛 `OtcApiException` |
| 中 | Prompt 漂移导致 LLM 输出格式变化 | 同一意图的多个 case 同时 fail |
| 中 | 上游字段缺失（如 `quote_content` 为空但下游节点假设非空）| trace 显示同一节点上游 state 字段缺失 |
| 低 | LangGraph 路由 bug（产品类型识别错误进入错误子图）| trace 显示 `route_product` decision 与 raw_text 不匹配 |
| 低 | MySQL Checkpointer 写延迟拖慢 timeout | trace 显示节点 `elapsed_ms` 异常大 |

### 1.3 诊断步骤

```bash
# 1. LangFuse 查最近 1 小时 fallback 触发率
#    打开 LangFuse → Traces → 按 metadata.fallback_triggered=true 过滤

# 2. 按 suspected_node 字段聚类，找共性
#    Traces → Group by → fail_node 字段（来自 @safe_node 写入的 error）

# 3. 如多数同节点 → 该节点 prompt / Pydantic 模型 / 后端调用有问题
#    查具体 trace 看 LLM input / output / 错误堆栈
#    重点字段：`llm_input` / `llm_raw_output` / `validation_errors`

# 4. 如多数同 LLM 类型（如所有 extract 节点都炸）→ LLM 后端问题
#    LangFuse → LLM latency 看是否有趋势漂移
#    检查 DeepSeek API 状态：curl https://api.deepseek.com/v1/models

# 5. 如不同节点散布 → 系统性问题
#    检查 MySQL：SHOW PROCESSLIST 看是否有长事务锁表
#    检查 Java 后端：连续 curl /admin-api/health 看 5xx 率
```

### 1.4 修复方案

| 根因 | 修复 |
|---|---|
| LLM 输出格式偏差 | git 里的提示词是唯一真源：`git revert` 对应 `prompt(<scope>)` 提交 + 应用重启；灰度中的版本可改 `_versions.yaml` 权重回退（ADR 0003）。生产禁止从 LangFuse 拉提示词（ADR 0014） |
| 后端 5xx 引发 | 见 §3 后端 5xx playbook；本节点的 fallback 路径应已写好降级 |
| Prompt 漂移 | 检查最近 PR 是否改了相关 prompt；按 ADR 0001 D5 处置表 review；必要时回滚 |
| 上游字段缺失 | 看 `ingest` 节点是否正常解析；节点入口加防御代码（`if not state.get("xxx"): return fallback`），属于**业务防御性编程**改动，不涉及 ADR |
| 路由 bug | 检查 `app/nodes/route_rules.py`；补关键词 / 正则；提 PR |
| MySQL 拖慢 | 见 §4 Checkpointer playbook |

### 1.5 禁忌

- **不要**直接禁用 `safe_node` 装饰——会让节点崩溃直接传到 API 层 5xx
- **不要**为了"消失 cascade"批量 hotfix 多个节点——找根因再修
- **不要**用 prompt 热更修代码层 bug——LangFuse Prompt 只能改 prompt 内容，不能改 Pydantic 模型

### 1.6 修复后验证

- LangFuse fallback 触发率 < 1% 持续 30 分钟
- 抽 5 条原本 fail 的真实输入重跑，全部 PASS
- 业务方反馈停止"听不懂"投诉
- 写故障报告归档到 `docs/incident-reports/`

---

## 2. LLM 超时 / 调用失败

### 2.1 识别信号

- LangFuse 仪表盘：LLM 调用失败率 ≥ 10% 持续 5 分钟（对齐 ADR 0019 P1 阈值）
- 应用日志：批量 `httpx.TimeoutException` / `httpx.ReadTimeout`
- 业务方反馈："AI 半天不回我"、"消息发了没反应"
- 严重程度：P1

### 2.2 可能根因

| 概率 | 根因 | 信号 |
|---|---|---|
| 高 | DeepSeek API 不通（公网中断/服务故障）| `curl api.deepseek.com` 不通 |
| 高 | 上下文超过模型 limit（特别是 swap.place_order 长 prompt）| 错误返回 `context_length_exceeded` |
| 中 | API key 失效 / 配额耗尽 | 错误返回 401 / 429 |
| 中 | 网络抖动 / 公司代理不稳定 | 间歇性超时，非持续 |
| 低 | 模型已下线 / 模型名称错误 | 错误返回 `model_not_found` |
| 低 | DeepSeek 限流（concurrent / TPM）| 错误返回 429 + Retry-After 头 |

### 2.3 诊断步骤

```bash
# 1. DeepSeek API 连通性
curl -sf -m 10 https://api.deepseek.com/v1/models -H "Authorization: Bearer $LLM_API_KEY"

# 2. 检查 .env 中 API key 与 base URL
grep -E "LLM_API|QWEN_API" /etc/otc-agent/.env

# 3. 看 LangFuse trace 的 LLM 错误信息
#    Traces → 按 metadata.llm_error=true 过滤 → 看错误码

# 4. 看应用 LLM 调用堆栈
journalctl -u otc-agent --since "10 minutes ago" | grep -E "TimeoutException|httpx.error"

# 5. 测 context 超长
#    单独跑 swap.place_order：python -m harness run --case <swap_long_prompt_case>
```

### 2.4 修复方案

| 根因 | 修复 |
|---|---|
| DeepSeek 不通 | 走应急回滚（on-call runbook §7），等服务恢复后切回 |
| Context 超长 | 检查 prompt 是否被无限累加（多轮对话 history 失控）；硬性截断或排查 ingest |
| API key 失效 | 客户 IT 重新申请 key；改 .env；重启应用 |
| 配额耗尽 | 联系客户提升配额；临时切到 backup model（如 fallback Qwen）|
| 网络抖动 | 增大 httpx timeout / 加 tenacity retry；非长久方案 |
| 限流 | 在客户端加并发限制（asyncio.Semaphore）；联系 DeepSeek 提升配额 |

### 2.5 禁忌

- **不要**临时把 timeout 拉到 300 秒——会拖死整个应用线程池
- **不要**在 prompt 没瘦身时切到更小 context 的模型——会触发 context_length_exceeded
- **不要**直接禁用 `with_structured_output` 改用手工 JSON 解析——违反 CLAUDE.md 原则 2

### 2.6 修复后验证

- LLM 失败率 < 1% 持续 30 分钟
- 跑 10 条 smoke case 全部 PASS（含 swap.place_order 长 prompt case）
- P95 LLM 延迟回到 baseline × 1.5 以内

---

## 3. Java 后端 5xx / 不可达

### 3.1 识别信号

- 应用日志：`OtcApiException` 批量出现 / `httpx.HTTPStatusError: 5xx`
- 业务方反馈："订单状态查不到"、"下单后没回执"
- 健康检查 `/ready` 返回 503（D2.6 落地后）
- 严重程度：P0（持续 ≥ 3 分钟）/ P1（间歇性）

### 3.2 可能根因

| 概率 | 根因 | 信号 |
|---|---|---|
| 高 | Java 后端服务挂了（崩溃 / 重启）| 所有 endpoint 同时 5xx |
| 高 | Java 后端依赖（业务 DB / GOATS）不通 | 业务 endpoint 5xx，健康检查 OK |
| 中 | Java 后端 token 过期 | 401 / 403（不是 5xx 但症状类似）|
| 中 | 应用与 Java 之间网络隔离 | curl 不通；ping 不通 |
| 低 | 业务参数非法（如标的代码格式错）触发 Java 异常 | 4xx 或 5xx，单条 case 触发 |
| 低 | Java 后端版本不兼容（业务方升级了）| 字段名变化 / 新增必填字段 |

### 3.3 诊断步骤

```bash
# 1. 单点 endpoint 联通测试
curl -sf -m 5 "$OTC_API_BASE_URL/admin-api/integration/securities-instrument/select" \
  -H "Token: $OTC_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"keywordItems":[{"keyword":"600519","isFull":false}]}'

# 期望返回：HTTP 200 + JSON 含 windCode 字段
# 5xx → Java 端出问题
# 401/403 → token 失效
# Timeout → 网络隔离

# 2. 多 endpoint 同时检查（找出哪些挂了）
for path in \
  "integration/securities-instrument/select" \
  "counterparty/info/instrument-inference-prompt" \
  "counterparty/info/list"; do
  printf "%-50s " "$path"
  curl -sf -m 5 -o /dev/null -w "%{http_code}\n" \
    "$OTC_API_BASE_URL/admin-api/$path" -H "Token: $OTC_API_SECRET"
done

# 3. 看 Java 后端日志（需要客户 IT 协助）
# 客户 IT 查 Java 应用日志：是否 OOM、是否依赖 down、是否 GC 卡死

# 4. 看应用侧错误聚类
journalctl -u otc-agent --since "10 minutes ago" | grep -E "OtcApiException|HTTPStatusError"
```

### 3.4 修复方案

| 根因 | 修复 |
|---|---|
| Java 后端挂了 | 联系客户 IT 重启 Java 服务；期间走 cascade fall fallback；可能升 P0 触发回滚 |
| Java 依赖不通 | 客户 IT 排查 Java 后端的下游（DB / GOATS） |
| Token 过期 | 客户 IT 提供新 token；改 .env；不重启（应用 lru_cache 5 分钟自动刷新）|
| 网络隔离 | 客户 IT 排查防火墙规则；可能企业网络变动 |
| 业务参数非法 | 看具体 case 用了什么参数；在对应节点（如 swap.cancel）入口加 input 验证（Pydantic 模型字段约束或显式守卫），属于业务防御性编程改动，无对应 ADR；不是回滚理由 |
| 版本不兼容 | 对照 `docs/api-contracts/java-backend.md` 看字段变化；走 hotfix 升级应用代码 |

### 3.5 禁忌

- **不要**直接绕过 Java 后端调用——这会让业务流程数据不一致
- **不要**用 mock 模式替代真后端跑生产——客户合规通常禁止
- **不要**为了"不报错"批量 swallow OtcApiException——隐藏问题反而更危险
- **不要**反复重试已知失败的 endpoint——可能加重 Java 后端负担

### 3.6 修复后验证

- 8 个 endpoint 全部连通测试通过
- 业务真实流程（下单 / 撤单 / 查询）跑 1 条端到端 case 全绿
- 应用日志连续 30 分钟无 OtcApiException
- 健康检查 `/ready` 持续返回 200

---

## 4. Checkpointer / MySQL 失败

### 4.1 识别信号

- 应用日志：`AIOMySQLSaver.aput failed` / `aiomysql.OperationalError` / `connection pool exhausted`
- 业务方反馈："AI 不记得我之前说过什么"（多轮对话失忆）
- 严重程度：P1（多轮对话受影响）

### 4.2 可能根因

| 概率 | 根因 | 信号 |
|---|---|---|
| 高 | MySQL 连接池打满 | 应用日志 "Pool exhausted, waited X sec" |
| 中 | MySQL 写锁竞争（其他业务在大量写）| SHOW PROCESSLIST 看到长事务 |
| 中 | MySQL 磁盘满 | `df -h` 看 MySQL 数据卷满 |
| 低 | MySQL 版本不兼容（如客户升级到 ≥ 9.6 触发 ADR 0009 警告）| 启动时 `await cp.setup()` 报错 |
| 低 | 账号权限不足（缺 DDL）| 启动时报 "Access denied for ALTER" |
| 低 | 字符集错（utf8 vs utf8mb4）| 中文 trace 内容报 "Incorrect string value" |

### 4.3 诊断步骤

```bash
# 1. MySQL 连通性
mysql -h <host> -u <user> -p<pass> -e "SELECT VERSION();"

# 2. 连接池状态（查应用配置）
grep -E "pool_size|max_overflow" app/checkpointer/factory.py

# 3. MySQL 当前连接数
mysql -e "SHOW STATUS LIKE 'Threads_connected'"
# 对比 max_connections：SHOW VARIABLES LIKE 'max_connections'

# 4. 长事务
mysql -e "SHOW PROCESSLIST" | awk '$6 > 30'  # 超过 30 秒

# 5. 磁盘空间
df -h /var/lib/mysql

# 6. MySQL 版本是否在 ADR 0009 范围
mysql -e "SELECT VERSION();"  # 必须 8.0.19 ≤ v < 9.6.0
```

### 4.4 修复方案

| 根因 | 修复 |
|---|---|
| 连接池打满 | 短期重启应用清理；长期扩 pool_size 或 MySQL max_connections |
| 写锁竞争 | 看长事务是哪个业务的；客户 DBA 协调 |
| 磁盘满 | 客户 IT 扩容 / 清理旧 checkpoint（参考 ADR 0014 D5 保留策略） |
| 版本不兼容 | 阻塞项 — 必须客户 IT 降级 MySQL 或我方换 Checkpointer 实现 |
| 权限不足 | 客户 DBA 补 GRANT；重启应用让 setup 重跑 |
| 字符集错 | ALTER DATABASE 改 utf8mb4 + 重新 setup checkpoint 表 |

### 4.5 禁忌

- **不要**禁用 Checkpointer 改用 InMemorySaver——多轮对话历史会全丢
- **不要**直接 DROP checkpoint 表"重置"——会丢业务对话上下文
- **不要**在出现连接池打满时把 pool_size 设到 1000——可能压垮 MySQL
- **不要**改 MySQL 字符集时不备份——容易导致历史 trace 中文乱码不可恢复

### 4.6 修复后验证

- 应用日志连续 30 分钟无 AIOMySQLSaver 错误
- 多轮对话 smoke：发一条带 conversation_id 的消息，再发一条引用上一条，AI 应记得上下文
- MySQL `Threads_connected` 稳定在 max_connections 50% 以下
- `langgraph_node_trace` 表持续写入新行

---

## 5. 故障案例库（部署后累加）

> 真实故障发生后，把对应 case 写入本节，标注：日期 / 故障类型 / 根因 / 修复 / 经验教训。
> 目标：5 个真实案例后这一节会成为团队最有价值的故障防御资产。

| # | 日期 | 类型 | 根因 | 修复 | 经验教训 |
|---|---|---|---|---|---|
| 1 | 待填 | — | — | — | — |

---

## 关联资源

- `docs/operations/on-call-runbook.md` · 值班手册（决策导向）
- `docs/development/troubleshooting.md` · 开发期 Q&A
- ADR 0009 · MySQL 版本兼容性硬约束
- ADR 0019 · 故障升级阈值（识别信号阈值依据）
- ADR 0030 · 评测门与上线观察指标
- `docs/api-contracts/java-backend.md` · Java 后端契约
- `docs/deploy/customer-private.md` · 部署手册
