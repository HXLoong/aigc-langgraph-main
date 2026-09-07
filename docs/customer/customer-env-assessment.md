# 客户环境调研报告（C1.9 模板）

> **版本**：v0.1 模板（2026-05-12）
> **状态**：模板——Tony 在客户现场逐项填实际值，填完后状态升级为"已调研"
> **目的**：在阶段 2 真后端联调（D2.1）启动**前**，把所有客户环境的关键参数 + 网络可达性 + 配置约束**一次性收集清楚**，避免联调时反复打扰客户 IT
> **预期填写时长**：现场半天到 1 天（含跑验证命令）

---

## 0. 调研方法论

### 0.1 谁来填

- **Tony** 主导：与客户 IT / 业务方对齐
- **图灵科技工程负责人 #25** 远程协助：当某项验证需要写测试代码时

### 0.2 怎么填

每个章节的表格里：
- **默认假设** = 基于 CLAUDE.md / ADR 0009-0018 的当前认知
- **实际值** = Tony 现场填的真实数据
- **验证步骤** = 在客户环境跑的命令或检查项
- **风险/备注** = 与默认假设不一致时如何处置

**填字段时遵循的纪律**：

- 不填 placeholder（如 "TBD"、"待定"）—— 不知道就写"未调研，原因 X"
- 敏感数据（password / API key / token）**不要直接写在本文档**——写"已存放至 1Password 团队保险库 / 客户企微保密群"，避免文档泄漏即出 secret 泄露
- 凡是"假设 ≥ X"的字段必须实测确认，不要靠"客户口头说应该有"

### 0.3 何时填完

- **必须**在 D2.1（阶段 2 真后端联调启动）**之前**填完所有 §3.1-3.8 必填项
- §3.9-3.11 可推到阶段 2 中段补完

---

## 1. 调研结果汇总（执行摘要，调研完成后填）

> 调研完成后在本节用 5-10 句话总结，让团队所有人 5 分钟内对客户环境形成共识。

**调研完成时间**：待填

**整体状态**：☐ 全部满足 LangGraph 部署条件 / ☐ 部分需调整 / ☐ 阻塞项需解决后再启动联调

**关键差异 / 风险**：待填

---

## 2. 客户基础设施

### 2.1 服务器与操作系统

| 项 | 默认假设 | 实际值 | 验证步骤 | 备注 |
|---|---|---|---|---|
| OS 发行版 | Ubuntu 22.04 / CentOS 7+ | 待填 | `cat /etc/os-release` | 若 Windows Server 需评估 docker compose 兼容性 |
| 内核版本 | Linux 5.x+ | 待填 | `uname -r` | — |
| CPU 核数 | ≥ 4 | 待填 | `nproc` | 应用主进程 + LangFuse 容器栈需 8 核更稳 |
| 内存 | ≥ 8 GB | 待填 | `free -h` | LangFuse 全栈 + MySQL 共需 4 GB+ |
| 磁盘空间 | ≥ 100 GB | 待填 | `df -h /` | trace + checkpoint 数据增长，6 个月 ≈ 50 GB |
| 服务器数量 | 1 台合并部署 OR 2 台拆分（app vs 数据） | 待填 | 客户 IT 询问 | 拆分部署对网络配置要求更高 |

### 2.2 Docker / 容器化

| 项 | 默认假设 | 实际值 | 验证步骤 | 备注 |
|---|---|---|---|---|
| Docker 版本 | ≥ 24.x | 待填 | `docker --version` | LangFuse 镜像需 ≥ 20 |
| Docker Compose | v2.x（plugin 形式） | 待填 | `docker compose version` | v1.x 旧版本 syntax 不兼容 |
| 镜像拉取能力 | 可访问 hub.docker.com 或客户内网镜像仓库 | 待填 | `docker pull alpine` | 不通 → C1.14 离线包介入 |
| root 或 docker group | 部署账号在 docker group | 待填 | `groups <user> \| grep docker` | 否则每次命令加 sudo 麻烦 |

---

## 3. 网络拓扑

### 3.1 公网可达性

| 目标 | 用途 | 必须可达 | 实测结果 | 验证命令 |
|---|---|---|---|---|
| `api.deepseek.com`（或客户指定 endpoint） | DeepSeek-v4-pro API 调用 | ✅ | 待填 | `curl -I https://api.deepseek.com -m 5` |
| `hub.docker.com` | Docker 镜像拉取 | 推荐 | 待填 | `docker pull hello-world` |
| `pypi.org` | pip 依赖安装 | 推荐 | 待填 | `pip install --dry-run langchain` |
| 客户企微回调地址 | 企微机器人 → LangGraph webhook | ✅ | 待填 | 企微管理员侧测试 |

**若上述任一不通**：标"阻塞 / 需走客户企业代理 / 走离线包"。

### 3.2 内网拓扑

| 项 | 实际值 | 备注 |
|---|---|---|
| LangGraph 应用监听端口 | 待填（默认 8000） | 与 Java 后端不同主机时需配防火墙规则 |
| MySQL 内网地址 | 待填 | Java 业务库 vs LangGraph checkpoint 库 |
| Java 后端内网地址 | 待填 | 含完整 base URL |
| LangFuse 内网地址 | 待填 | 部署后填，§7 |
| 企微回调入口（反向代理 / 端口转发） | 待填 | 是否有 HTTPS 证书 |

### 3.3 防火墙 / 端口

调研客户内网防火墙策略：

- LangGraph 应用对外暴露端口：______（默认 8000，需对企微 IP 段开放）
- LangFuse 管理后台暴露：______（默认 3000，**仅限内网 IT 与开发**）
- MySQL 端口：______（默认 3306，**绝不能对公网开放**）

---

## 4. MySQL（业务库 + Checkpoint）

> 见 ADR 0009 · MySQL 版本兼容性硬约束

| 项 | 默认假设 | 实际值 | 验证步骤 | 备注 |
|---|---|---|---|---|
| MySQL 版本 | **8.0.19 ≤ v < 9.6.0**（ADR 0009 硬约束）| 待填 | `mysql -e "SELECT VERSION();"` | 不符合则 `AIOMySQLSaver` 不可用 → 阻塞项 |
| 字符集 | utf8mb4 | 待填 | `SHOW VARIABLES LIKE 'character_set_database';` | 默认 utf8 / latin1 → 中文乱码 |
| 时区 | Asia/Shanghai 或 +08:00 | 待填 | `SELECT @@system_time_zone, @@global.time_zone;` | trace 时间戳错位 |
| max_connections | ≥ 200 | 待填 | `SHOW VARIABLES LIKE 'max_connections';` | LangGraph 连接池 50 + Java 应用 100+ |
| 业务库账号 | LangGraph 只读 + 业务系统 | 待填（账号不写本文档，存保险库）| 客户 IT 提供 | — |
| Checkpoint 库账号 | LangGraph 独立读写库 | 待填（账号不写本文档）| 建议新建库 `otc_agent_checkpoint` | 与业务库隔离 |
| Checkpoint 表存在 | 启动时 `await cp.setup()` 自动建 | 待填 | — | 失败 → 账号缺 DDL 权限 |

**已知风险**：客户若用 **TDSQL / OceanBase / PolarDB** 等国产兼容版本，须单独测试 `AIOMySQLSaver` 兼容性（ADR 0009 警告）。

---

## 5. Java 后端业务 API

> 见 `docs/api-contracts/java-backend.md` 完整契约

| 项 | 实际值 | 验证步骤 | 备注 |
|---|---|---|---|
| Java 后端基础 URL | 待填 | — | 含 `/admin-api` 前缀 |
| 认证方式 | 待填（`@PlatformApiAuth` token / OAuth / 内网信任）| `curl -H "Token: xxx" $URL/admin-api/integration/securities-instrument/select` | 与 ADR 0012 一致 |
| Token / Secret 来源 | 待填（存保险库）| 客户 IT 提供 | 轮转周期？ |
| 健康检查 endpoint | `/health` 或客户自定义 | `curl $URL/health` | C1.9 中验证 |
| 业务版本 | 待填（git tag / jar version）| 客户 IT 提供 | 与 `docs/api-contracts/` 编制日期对齐 |
| 时区一致性 | 与 LangGraph 一致 | 业务负责人确认 | 否则订单时间戳异常 |

**关键 endpoint 联通测试清单**（必须每条都验证）：

- [ ] `GET /admin-api/integration/securities-instrument/select`（ticker 解析）
- [ ] `GET /admin-api/counterparty/info/instrument-inference-prompt`（动态 prompt）
- [ ] `GET /admin-api/counterparty/info/list`
- [ ] `POST /admin-api/financial-orders/operate`（期权下单）
- [ ] `POST /admin-api/financial-orders/query-close-orders`（持仓查询）
- [ ] `POST /admin-api/swap-order/operate`（互换下单）
- [ ] `GET /admin-api/swap-order/get?orderId=xxx`
- [ ] `POST /admin-api/swap-order/get-conversation-orders`

每条至少跑一次 `curl` + 返回 `CommonResult.code = 0` 或合理错误码。

---

## 6. 大模型 API · DeepSeek-v4-pro

> 见 ADR 0018 · 开发 Qwen / 现场 DeepSeek 双模型分立

| 项 | 实际值 | 验证步骤 | 备注 |
|---|---|---|---|
| API endpoint | 待填（默认 `https://api.deepseek.com/v1`）| — | 客户若走企业代理需填代理地址 |
| API key 提供方 | 待填（客户 / 我方）| — | 与 ADR 0018 决策对齐 |
| API key 实际值 | 待填（**存保险库，不写本文档**）| — | — |
| 网络可达性 | 必须公网或代理可通 | `curl -H "Authorization: Bearer $KEY" $URL/chat/completions -d '...'` | 阻塞项 |
| 模型可用性 | `deepseek-v4-pro` 实际可调 | 用 curl 跑一条最简 chat completion | 验证模型名称无误 |
| 上下文窗口 | ≥ 128K（假设值） | 跑一条 50K tokens 输入测试 | swap.place_order 40K prompt 安全余量 |
| 结构化输出支持 | 支持 `response_format: json_object` | OpenAI 风格测试 | 24 节点全依赖 |
| Function calling 支持 | 支持 OpenAI 风格 tool calling | 跑 ticker ReAct 测试 | ticker 子图依赖 |
| 计费方 | 待填 | — | — |
| 月度 token 配额 | 待填 | — | 影响成本预算 |
| 流式输出 | 默认不用 | — | M3 不依赖 streaming |

---

## 7. LangFuse Self-Hosted 部署位置

| 项 | 实际值 | 备注 |
|---|---|---|
| 部署主机 | 待填 | 与 LangGraph 同机 / 独立机 |
| 暴露端口 | 待填（默认 3000）| 仅内网 |
| 持久化数据卷路径 | 待填 | trace + dataset 数据 |
| PostgreSQL / ClickHouse / Redis / MinIO 启动状态 | 待填 | 5 个容器全部跑通 |
| 管理员账号创建 | 待填（账号存保险库）| 首次启动 web 控制台时初始化 |
| 项目 / API key 配置 | 待填（key 存保险库）| 部署 LangFuse 后自动生成 |

**部署步骤参考**：`infra/langfuse/docker-compose.yml`（M1 已建好）

---

## 8. 企微机器人配置

| 项 | 实际值 | 备注 |
|---|---|---|
| 企微企业 ID（corp_id） | 待填（不写完整，仅末 4 位 + 描述）| 保密 |
| 应用 ID（agent_id） | 待填 | — |
| 应用 Secret | 待填（存保险库）| — |
| 当前 Webhook URL（指向 Dify） | 待填 | 紧急回滚目标 |
| 部署后切换 Webhook URL（指向 LangGraph） | 待填 | 含完整 HTTPS 入口 |
| 加密通道 | 必须 HTTPS | 企微强制要求 |
| 企微管理员 | 待填（姓名 + 企微 ID） | C1.16 runbook 联系人 |

---

## 9. 监控告警接收

| 项 | 实际值 | 备注 |
|---|---|---|
| 工程团队告警群（企微）| 待填（群名 + 群号） | C1.6 告警目标 |
| LangFuse 监控仪表盘访问列表 | 待填 | 内网 IP 段或 SSO |
| 邮件告警地址（备份）| 待填 | 重大故障兜底 |
| 业务方反馈通道 | 待填 | sign-off 人 + 备用 |

---

## 10. 时区 / 语言 / 编码

| 项 | 默认 | 实际值 |
|---|---|---|
| 服务器时区 | Asia/Shanghai | 待填 |
| MySQL 时区 | +08:00 | 待填 |
| Java 后端时区 | Asia/Shanghai | 待填 |
| 系统语言 | zh_CN.UTF-8 | 待填 |
| 文件编码 | UTF-8 | 待填 |

**全栈时区必须一致**——否则 trace / checkpoint / 业务时间戳错位会让故障诊断极度困难。

---

## 11. 数据保留 / 合规要求

| 项 | 客户要求 | 备注 |
|---|---|---|
| trace 数据保留期限 | 待填 | 影响 LangFuse 存储规划 |
| 是否允许 trace 数据出客户内网 | 默认**否** | self-hosted 即满足 |
| 业务订单日志保留 | 待填 | 通常 ≥ 7 年（金融合规）|
| 用户输入（企微消息）是否敏感 | 默认**否**（客户群内业务消息）| 客户合规确认 |
| 出境数据合规 | 默认**不出境** | DeepSeek 公网调用 = 数据出境，需客户合规明确允许 |

> **关键风险**：DeepSeek API 调用走公网 = 用户输入会到 DeepSeek 服务器。客户合规上是否接受？必须在调研中明确确认，不能假设。

---

## 12. 现场联系人通讯录（C1.16 runbook 附录 A 来源）

> 调研中收集，回填到 `docs/on-call-runbook.md` 附录 A。

| 角色 | 姓名 | 企微 / 电话 | 备用联系 |
|---|---|---|---|
| 客户企微管理员 | 待填 | 待填 | — |
| 客户 IT 负责人 | 待填 | 待填 | — |
| 客户业务方负责人（sign-off 人） | 待填 | 待填 | — |
| 客户 DBA | 待填 | 待填 | — |
| 客户网络管理员 | 待填 | 待填 | — |

---

## 13. 风险登记表

| 风险项 | 概率 | 影响 | 应对计划 |
|---|---|---|---|
| MySQL 版本不在 8.0.19-9.6.0 区间 | 低 | 阻塞 | 升级 MySQL 或换 Checkpointer（成本高）|
| DeepSeek API 不通 | 低 | 阻塞 | 配代理 / 切回 Qwen |
| Java 后端 token 频繁过期 | 中 | 高 | 接 OAuth refresh 或长有效期 token |
| LangFuse 内网部署 OOM | 中 | 中 | 拆机或缩配置（disable ClickHouse 用 PG 备选）|
| 客户数据出境合规未明确 | 中 | 高 | sign-off 前必须有书面 OK |
| Webhook HTTPS 证书过期 | 低 | 高 | 监控证书有效期 |

---

## 14. 调研完成签字

| 项 | 完成日期 | 签字 |
|---|---|---|
| Tony 调研结束 | 待填 | Tony |
| #25 工程负责人 review | 待填 | #25 |
| 客户 IT 信息确认 | 待填 | 客户 IT 联系人 |

---

## 关联资源

- **路线图 C1.9 / C1.10 / C1.11-C1.14**（`docs/m3-m4-roadmap.md`）—— 本调研是这几个任务的输入
- **ADR 0009** · MySQL 版本兼容性硬约束（§4 依据）
- **ADR 0012** · `securities-instrument/select` 后端 HTTP 路径（§5 依据）
- **ADR 0013** · 动态推断 prompt 后端拉取（§5 endpoint 清单）
- **ADR 0018** · 双模型分立（§6 依据）
- **`docs/api-contracts/java-backend.md`** · Java 业务 API 完整契约
- **`docs/on-call-runbook.md`** · C1.16 草稿，附录 A 联系人由本调研 §12 回填
- **CONTEXT.md** · 项目术语
