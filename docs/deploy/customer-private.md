# 客户现场私有化部署手册

> **版本**：v1.0（2026-05-12）
> **适用范围**：otc-agent 在客户内网完整部署（应用 + MySQL + LangFuse + 企微接入）
> **预期时长**：首次部署 4-6 小时（含资源准备）；熟练后 30 分钟可重复
> **关联**：LangFuse self-hosted 部署 / `scripts/deploy-customer.sh` 一键脚本（推荐用脚本而非手工执行本文）

本文档面向**客户 IT 运维**。10 个步骤从零到 LangGraph 应用接入企微生产，每步都给验证命令。

---

## 0. 部署前必读

### 0.1 谁要看本文档

- 客户 IT 运维（执行者）
- 图灵科技工程负责人（远程支持）
- Tony（项目协调）

### 0.2 部署前提

完成以下 4 件事**之前**不要启动部署：

1. ✅ `docs/deploy/customer-env-assessment.md` 14 节调研填完整（所有"待填"字段都有真实值）
2. ✅ MySQL 已创建好 2 个库（业务库 + checkpoint 库），账号权限就位
3. ✅ DeepSeek-v4-pro API Key 拿到（开发期我方提供，现场客户对齐）
4. ✅ Java 后端可达（curl 测试 8 endpoints 至少有 1 返回 CommonResult）

### 0.3 自动化 vs 手工

**推荐**：用 `scripts/deploy-customer.sh`（一键脚本）。本文档是脚本失败时的手工备份路径，以及理解每步在做什么的参考。

---

## 1. 主机准备

参考 `docs/deploy/customer-env-assessment.md` §2 部署前检查清单。最低配置：

- OS：Ubuntu 22.04 / CentOS 7+ / RHEL 8+
- CPU：8 核
- 内存：16 GB（应用 + MySQL + LangFuse 全栈同机）
- 磁盘：100 GB
- Docker：≥ 24.x，docker compose v2.x

**验证**：

```bash
nproc                          # ≥ 8
free -h                        # ≥ 16 GB
df -h /                        # ≥ 100 GB
docker --version               # ≥ 24
docker compose version         # ≥ v2
groups $USER | grep docker     # 必有 docker 组
```

---

## 2. 准备 MySQL

参考 ADR 0009：MySQL 版本必须 **8.0.19 ≤ v < 9.6.0**。

### 2.1 验证版本

```bash
mysql -h <HOST> -u <USER> -p -e "SELECT VERSION();"
# 期望返回如 "8.0.32"
```

不在版本区间内 → 阻塞，必须升级或换 Checkpointer（成本高，找工程团队评估）。

### 2.2 在 Java 现有数据库初始化 LangGraph 表

使用已有账号连接 Java 数据库，由连接参数选择库；SQL 不创建数据库、不包含 USE 或授权。

```bash
mysql -h <HOST> -P <PORT> -u <USER> -p --database=<JAVA_DATABASE> < sql/init.sql
```

九张表均带 `langgraph_` 前缀，使用 `utf8mb4_general_ci`。只需配置 `MYSQL_URI`，选择 Java 现有数据库。
应用启动只校验结构和版本，不自动建表；运行账号只需自身前缀表的读写权限及元数据可见性。
初始化/后续结构升级由具备 DDL 权限的部署账号执行。旧独立库保留，不自动迁移、删除历史。
容器访问宿主机 MySQL 时使用 `host.docker.internal`，不要在容器内使用 localhost 指代宿主机。

### 2.3 时区一致性

确认 MySQL 时区与应用时区一致：

```sql
SELECT @@system_time_zone, @@global.time_zone;
-- 期望 Asia/Shanghai 或 +08:00
```

如不一致 → 改 my.cnf 中 `default-time-zone = '+08:00'` 重启。

---

## 3. 部署 LangFuse Self-Hosted

详见 [`docs/langfuse/self-hosted-deployment.md`](../langfuse/self-hosted-deployment.md)。

简版步骤：

```bash
cd <repo>/infra/langfuse

# 1. .env
cp .env.example .env
echo "SALT=$(openssl rand -base64 32)" >> .env
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "NEXTAUTH_SECRET=$(openssl rand -base64 32)" >> .env
# 编辑 .env 改 4 个默认密码

# 2. 启动
docker compose --env-file .env up -d

# 3. 等 7 个容器全 healthy（约 30-60 秒）
docker compose --env-file .env ps

# 4. 浏览器访问 http://<host>:3000，注册账号 → 创建项目 → 复制 pk/sk
```

记下 `pk-lf-...` + `sk-lf-...`，下一步填到应用 .env。

---

## 4. 配置应用 .env

### 4.1 准备文件

```bash
cd <repo>

cp .env.customer.template .env
nano .env  # 替换所有 <FILL_*> 占位符
chmod 600 .env  # 限制读权限
```

### 4.2 必填字段清单

参考 `.env.customer.template` 11 节注释。最少必填：

- `MYSQL_URI`（§2）
- `QWEN_API_BASE` / `QWEN_API_KEY` / `QWEN_MODEL_STANDARD`（DeepSeek）
- `OTC_API_BASE_URL` / `OTC_API_SECRET`
- `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`（§3）

### 4.3 验证

```bash
# 用 Python 加载验证（不启动应用）
python -c "from app.config import get_settings; s = get_settings(); print('OK')"
# 必报错 → 检查缺哪个字段
```

---

## 5. 安装 Python 依赖

### 5.1 有公网

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### 5.2 离线（无公网）

参考离线包流程：

```bash
# 从客户提供的离线包导入
tar xzf otc-agent-offline-bundle.tar.gz
pip install --no-index --find-links=wheelhouse -e ".[dev]"
```

### 5.3 验证

```bash
python -c "import app; print(app.__file__)"
# 必输出实际路径
```

---

## 6. 启动应用

### 6.1 开发期手工启动（调试用）

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6.2 生产用 systemd 服务

```bash
sudo cp scripts/otc-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable otc-agent
sudo systemctl start otc-agent
sudo systemctl status otc-agent
```

### 6.3 验证启动

```bash
# 看日志
journalctl -u otc-agent -f

# 期望看到 "Uvicorn running on http://0.0.0.0:8000"
```

---

## 7. 健康检查

```bash
# 应用本地健康检查
curl http://localhost:8000/health
# 期望返回 200 + JSON

# 健康检查 endpoint 校验 4 个上游
# 临时验证：
curl http://localhost:8000/v1/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"raw_text":"测试"},"response_mode":"blocking","user":"smoke"}'
# 期望返回有 reply_text 字段的 JSON
```

如某一项失败 → 见 [`docs/operations/on-call-runbook.md`](../operations/on-call-runbook.md) §5 故障 playbook。

---

## 8. 接入企微

### 8.1 配置企微机器人 Webhook

企微管理员后台：

1. 应用管理 → 自建应用 → 创建（或编辑）otc-agent 机器人
2. Webhook URL：`https://<reverse-proxy>/v1/workflows/run`
   - **必须 HTTPS**（企微强制）
   - 反向代理（nginx）把 LangGraph 8000 端口经 443 SSL 暴露
3. 验证：在测试群发"测试"，应用日志看到接收请求

### 8.2 反向代理示例（nginx）

```nginx
server {
    listen 443 ssl http2;
    server_name otc-agent.customer.internal;

    ssl_certificate     /etc/ssl/customer.crt;
    ssl_certificate_key /etc/ssl/customer.key;

    location /v1/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;  # 长 prompt + LLM 响应可能 > 60s
    }
}
```

### 8.3 验证

测试群发 "@otc-agent 600519.SH 询价" → 应该看到询价回复。

---

## 9. Smoke 自检（3 条 case）

部署完成后**必须**跑 3 条 smoke 验证全链路：

### Case 1：完整代码 + 简单询价

```bash
curl http://localhost:8000/v1/workflows/run \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "raw_text": "600519.SH 询价 3 个月平值看涨",
      "conversation_id": "smoke-001"
    },
    "response_mode": "blocking",
    "user": "smoke-test"
  }'

# 期望：reply_text 含 "询价" + "600519.SH" + 期限/期权类型字段
```

### Case 2：中文简称

```bash
curl ... -d '{"inputs":{"raw_text":"贵州茅台 询价"...}'
# 期望：reply_text 含 "600519.SH 贵州茅台"
```

### Case 3：未知标的（fallback）

```bash
curl ... -d '{"inputs":{"raw_text":"完全不存在的标的xyz 询价"...}'
# 期望：reply_text 含 "抱歉，无法识别"
```

3 条全 OK → 部署成功。

---

## 10. 故障排查

按 `docs/operations/on-call-runbook.md` §5 五类故障 playbook 处理：

| 现象 | playbook |
|---|---|
| 应用启动失败 | §5.1 LangGraph 5xx 崩溃（看 stack） |
| 5xx / 超时 | §5.1 / §5.4 |
| HITL 不响应 | §5.3 |
| trace 不显示 | §5.5 LangFuse 不可达 |
| 多轮对话失忆 | §5.6 MySQL Checkpointer 失败 |

故障升级路径：客户 IT 自查（本文档 + on-call runbook）→ 图灵科技工程负责人 → Tony。

---

## 11. 部署后日常

| 任务 | 频率 | 文档 |
|---|---|---|
| 备份 LangFuse 数据 | 周备份 | `docs/langfuse/self-hosted-deployment.md` §5 |
| 监控告警检查 | 每日（自动化）| 告警接线后 |
| 应用日志归档 | 按客户合规要求 | 安全审计后再细化 |
| API Key 轮转 | 按客户合规要求 | 安全审计后再细化 |
| 版本升级 | minor 月度 / major 视客户需求 | `docs/langfuse/self-hosted-deployment.md` §7 |

---

## 关联资源

- `.env.customer.template`（本目录的 env 模板）
- [`docs/deploy/customer-env-assessment.md`](customer-env-assessment.md) · 部署前调研清单
- [`docs/langfuse/self-hosted-deployment.md`](../langfuse/self-hosted-deployment.md) · LangFuse 部署详解
- [`docs/operations/on-call-runbook.md`](../operations/on-call-runbook.md) · 故障 playbook
- [`docs/api-contracts/java-backend.md`](../api-contracts/java-backend.md) · Java 后端契约
- ADR 0009 · MySQL 版本兼容性
- ADR 0014 · LangFuse 后端
- ADR 0020 · 全量 DeepSeek-V4-pro
- `scripts/deploy-customer.sh`
