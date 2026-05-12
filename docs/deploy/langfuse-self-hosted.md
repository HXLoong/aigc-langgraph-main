# LangFuse Self-Hosted 客户内网部署手册

> **版本**：v1.0（2026-05-12）
> **适用范围**：客户内网私有化部署（无 SaaS 依赖），承载 LangGraph 应用的 trace / dataset / eval / annotation
> **关联**：ADR 0014 · LangFuse 作为 Harness 后端 / `infra/langfuse/` · 部署资产

本文档面向**客户 IT 运维**，让其零外援即可在内网把 LangFuse 跑起来。`infra/langfuse/README.md` 是开发期 quick-start；本文档是生产部署的完整指南。

---

## 1. 部署前检查清单

执行 `infra/langfuse/docker-compose.yml` 前，验证以下条件：

### 1.1 主机资源

| 项 | 最低要求 | 推荐 | 验证命令 |
|---|---|---|---|
| CPU 核数 | 4 | 8 | `nproc` |
| 内存 | 4 GB | 8 GB | `free -h` |
| 磁盘空间 | 30 GB | 100 GB | `df -h /var/lib/docker` |
| Docker | ≥ 24.x | latest stable | `docker --version` |
| Docker Compose | v2.x（plugin） | latest | `docker compose version` |

> **OOM 风险**：ClickHouse + Postgres + MinIO 同机部署，4 GB 内存接近边界。生产环境推荐 8 GB+。

### 1.2 端口占用

LangFuse 全栈占 6 个端口，部署前确认未被占用：

```bash
# 在部署主机执行
for port in 3000 3030 5432 8123 6379 9090 9091; do
  ss -tlnp | grep ":$port " && echo "❌ 端口 $port 已被占用"
done
```

| 端口 | 服务 | 是否对外暴露 |
|---|---|---|
| 3000 | langfuse-web（UI + API） | **是**（限内网；外部访问需反代）|
| 3030 | langfuse-worker | 否（仅内部）|
| 5432 | postgres | 否（仅内部）|
| 8123 | clickhouse HTTP | 否（仅内部）|
| 9000 | clickhouse native | 否（仅内部）|
| 9090 | minio S3 API | 否（仅内部）|
| 9091 | minio 管理控制台 | 调试时临时打开 |
| 6379 | redis | 否（仅内部）|

可通过修改 `.env` 中 `*_PORT` 变量改默认值（如客户内网已有 PG 占 5432，可改为 15432）。

### 1.3 网络出口

| 资源 | 用途 | 是否必须 |
|---|---|---|
| Docker Hub `hub.docker.com` | 拉取 langfuse / postgres / clickhouse / redis / minio 镜像 | 推荐 |
| 客户内网镜像仓库 | 离线场景从内部仓库拉镜像 | 离线场景必须 |

**离线部署**：参考 C1.14（#59）的离线包导入流程。

### 1.4 持久化卷

LangFuse 用 4 个 docker named volume 持久化数据：

| 卷名 | 内容 | 容量增长 |
|---|---|---|
| `langfuse_postgres_data` | 元数据（项目 / 用户 / API key / dataset） | 慢；100 MB 即可 |
| `langfuse_clickhouse_data` | trace 时序（核心数据）| 快；按 trace 量预估见 §6 |
| `langfuse_clickhouse_logs` | ClickHouse 日志 | 慢；100 MB |
| `langfuse_minio_data` | trace 大块归档 + 媒体上传 | 中；按 trace 量 30% |

确认 Docker 卷宿主路径有足够空间：

```bash
docker info | grep "Docker Root Dir"
# 默认 /var/lib/docker；保证该挂载点磁盘 ≥ 30 GB（trace 一年）/ ≥ 100 GB（trace 五年）
```

---

## 2. 启动流程

### 2.1 准备配置

```bash
cd infra/langfuse

# 复制 .env 模板
cp .env.example .env

# 生成 3 个强制密钥（首次部署必须）
echo "SALT=$(openssl rand -base64 32)" >> .env
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "NEXTAUTH_SECRET=$(openssl rand -base64 32)" >> .env

# 修改默认密码（生产环境必须！.env.example 默认值不可用于生产）
# 用编辑器打开 .env，替换以下值为强密码（≥ 32 字符随机串）：
#   POSTGRES_PASSWORD
#   CLICKHOUSE_PASSWORD
#   MINIO_ROOT_PASSWORD
#   REDIS_AUTH
```

> **安全约束**：`.env` 含全部密钥与密码，**绝不能 commit 到 git**。已在 `.gitignore`，但部署后 chmod 600 `.env` 限制只允许 root 读。

### 2.2 启动容器

```bash
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d
```

等待容器全部 healthy（首次启动 + ClickHouse migration 约 30-60 秒）：

```bash
# 监控启动进度
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env ps

# 期望输出（5 个 backing + 2 个 langfuse 共 7 个容器）：
# NAME                    STATUS                         PORTS
# langfuse-postgres-1     Up (healthy)
# langfuse-clickhouse-1   Up (healthy)
# langfuse-minio-1        Up (healthy)
# langfuse-redis-1        Up (healthy)
# langfuse-worker-1       Up                             0.0.0.0:3030->3030/tcp
# langfuse-web-1          Up                             0.0.0.0:3000->3000/tcp
```

### 2.3 启动顺序与依赖

`docker-compose.yml` 用 `depends_on: condition: service_healthy` 自动保证：

```
postgres (健康) ──┐
clickhouse (健康) ─┤
minio (健康) ──────┼──→ worker + web 启动
redis (健康) ──────┘
```

启动期间不要手工 restart——会破坏 ClickHouse migration 进度，需要清空数据卷重来。

---

## 3. 首次配置（Web 控制台）

### 3.1 创建管理员账号

浏览器访问 `http://<langfuse-host>:3000`（生产建议挂 HTTPS 反代）：

1. 点击 "Sign up" 注册第一个用户（自动成为该实例的 admin）
2. 填邮箱 + 强密码（**记入保密文档，不要明文存任何代码库**）
3. 完成注册后会跳转到 dashboard

> 客户内网部署后，可在 `.env` 设置 `LANGFUSE_INIT_*` 一组变量提前注入初始组织/项目/用户，避免手工创建。详见 docker-compose.yml line 149-157。

### 3.2 创建组织 + 项目

1. 左侧菜单 "Organizations" → "New Organization"，命名如 `图灵科技-客户名`
2. 进入组织后 "Projects" → "New Project"，命名如 `otc-agent-prod`
3. 进入项目 → "Settings" → "API Keys" → "Create API Key"
4. 复制 `pk-lf-...`（public） + `sk-lf-...`（secret）

### 3.3 注入到 LangGraph 应用

把上一步的 API Key 写到 LangGraph 应用的 `.env`（参考 C1.12 模板）：

```bash
LANGFUSE_HOST=http://<langfuse-host>:3000
LANGFUSE_PUBLIC_KEY=pk-lf-xxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxx
ENABLE_LANGFUSE=true
```

重启 LangGraph 应用，发一条测试请求，1 分钟内 Langfuse `Traces` 页应出现该 trace。

---

## 4. 反向代理 + HTTPS（生产推荐）

LangFuse Web 默认 HTTP 暴露在 3000 端口；生产强烈推荐挂 nginx + HTTPS 证书：

```nginx
# /etc/nginx/conf.d/langfuse.conf
server {
    listen 443 ssl http2;
    server_name langfuse.customer.internal;

    ssl_certificate     /etc/ssl/customer.crt;
    ssl_certificate_key /etc/ssl/customer.key;

    location / {
        proxy_pass         http://127.0.0.1:3000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        # LangFuse WebSocket（实时仪表盘）
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
    }
}
```

同步把 `.env` 的 `NEXTAUTH_URL` 改成 `https://langfuse.customer.internal`，否则跳转链接会回到 http://localhost:3000。

---

## 5. 数据持久化与备份

### 5.1 备份策略

ADR 0014 D6 数据保留策略：

| 类型 | 保留期 | 备份频率 | 备份目标 |
|---|---|---|---|
| Trace | 90 天 | 周备份（增量） | 客户内网备份系统 |
| Dataset | 永久 | 日备份（增量） | 客户内网备份系统 |
| Score | 永久 | 日备份 | 客户内网备份系统 |
| Annotation | 永久 | 日备份 | 客户内网备份系统 |

### 5.2 Postgres 备份命令

```bash
# 完整备份
docker exec langfuse-postgres-1 pg_dump -U postgres -F c postgres > pg-backup-$(date +%F).dump

# 恢复
docker exec -i langfuse-postgres-1 pg_restore -U postgres -d postgres < pg-backup-2026-05-12.dump
```

### 5.3 ClickHouse 备份

```bash
# 完整快照（使用 docker volume）
docker run --rm \
  -v langfuse_clickhouse_data:/source \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/clickhouse-$(date +%F).tar.gz -C /source .

# 恢复（停容器后）
docker compose -f infra/langfuse/docker-compose.yml down
docker run --rm \
  -v langfuse_clickhouse_data:/target \
  -v $(pwd)/backups:/backup \
  alpine sh -c 'cd /target && tar xzf /backup/clickhouse-2026-05-12.tar.gz'
docker compose -f infra/langfuse/docker-compose.yml up -d
```

### 5.4 MinIO 备份

```bash
# MinIO 用 mc 工具镜像备份
docker run --rm --network host \
  -e MC_HOST_local=http://minio:miniosecret@localhost:9090 \
  minio/mc mirror local/langfuse /backup/minio-langfuse/
```

---

## 6. 容量规划

### 6.1 trace 数据增长估算

假设客户日均流量 100-200 条用户消息：

| 项 | 单条数据量 | 月数据量（150 条/天 × 30 天） |
|---|---|---|
| ClickHouse trace 行 | ~ 5 KB（含 span / event） | ~ 22 MB |
| MinIO 大块归档（input/output JSON） | ~ 50 KB | ~ 225 MB |
| Postgres 元数据 | ~ 0.5 KB | ~ 2 MB |
| **合计** | ~ 55 KB | **~ 250 MB/月** |

90 天保留期总占用：**~ 750 MB**（ClickHouse + MinIO 主要）。

5 年累计（如保留期延长至永久）：**~ 15 GB**——单机部署绰绰有余。

### 6.2 trace 量暴涨预警

若日 trace 数突增 ≥ 30% 触发告警（C1.6 #55 / C1.7 #56 联动）：

- 可能原因：业务量增长 / 调试漏关 trace / cascade fail 循环触发
- 处置：先查 LangFuse dashboard 哪些 project 暴涨；定位异常调用方
- 如纯业务增长：扩 ClickHouse / MinIO 存储或缩短保留期

---

## 7. 升级路径

LangFuse v3.x 内 minor / patch 升级：

```bash
# 1. 备份（参考 §5）
# 2. 拉新 image
docker compose -f infra/langfuse/docker-compose.yml pull langfuse-web langfuse-worker

# 3. 重启
docker compose -f infra/langfuse/docker-compose.yml up -d --no-deps langfuse-web langfuse-worker

# 4. 验证 /api/public/health 返回 200
curl http://localhost:3000/api/public/health
```

major 版本（v3 → v4）升级**必须**先在测试环境完整验证 ClickHouse migration 不丢数据；生产升级前先备份所有卷。

---

## 8. 常见问题诊断

### 8.1 启动后 langfuse-web 一直 restarting

最常见原因：3 个密钥（SALT / ENCRYPTION_KEY / NEXTAUTH_SECRET）未生成或被注释。

```bash
# 查日志确认
docker logs langfuse-web-1 2>&1 | grep -E "SALT|ENCRYPTION_KEY|NEXTAUTH_SECRET"

# 必看到 "SALT is required" / "ENCRYPTION_KEY is required" 错误
# 解决：执行 §2.1 的 openssl 命令补全密钥后 docker compose up -d
```

### 8.2 OOM Killed

ClickHouse 默认占用大量内存。低配机器（4 GB）需限制：

```yaml
# docker-compose.yml 给 langfuse-clickhouse 加：
deploy:
  resources:
    limits:
      memory: 2g
```

### 8.3 端口冲突

`.env` 中 `*_PORT` 变量改默认值（如 LangFuse 主端口从 3000 → 13000）：

```bash
LANGFUSE_PORT=13000
```

注意：改了 `LANGFUSE_PORT` 后，应用的 `LANGFUSE_HOST` 也要同步改成 `http://host:13000`。

### 8.4 ClickHouse migration 失败

通常发生在低内存机器或网络中断时。**唯一干净的恢复**是清空卷重来（会丢现有 trace 数据；生产环境要先备份）：

```bash
docker compose -f infra/langfuse/docker-compose.yml down -v
# 重新 up
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d
```

### 8.5 trace 不显示

应用 ENABLE_LANGFUSE 没开 / key 错 / 网络不通。逐项排查：

```bash
# 1. 应用日志看 LangFuse callback 错误
grep -i "langfuse" /var/log/otc-agent/*.log

# 2. 测试连接
curl -u $LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY $LANGFUSE_HOST/api/public/health

# 3. 期望返回 200 + JSON {"status": "OK"}
```

---

## 9. 关停与清理

```bash
# 关停（保留数据，可重启）
docker compose -f infra/langfuse/docker-compose.yml down

# 关停并删 4 个数据卷（**永久丢数据，谨慎！**）
docker compose -f infra/langfuse/docker-compose.yml down -v

# 仅清理日志卷（保留主数据）
docker volume rm langfuse_clickhouse_logs
```

---

## 10. 联系人 + 关联文档

| 资源 | 位置 |
|---|---|
| Quick start | `infra/langfuse/README.md` |
| docker-compose 配置 | `infra/langfuse/docker-compose.yml` |
| .env 模板 | `infra/langfuse/.env.example` |
| ADR | [ADR 0014 · LangFuse 作为 Harness 后端](../adr/0014-langfuse-as-harness-backend.md) |
| 客户环境调研 §7 | [`docs/customer-env-assessment.md`](../customer-env-assessment.md) |
| On-call runbook §5.5 | [`docs/on-call-runbook.md`](../on-call-runbook.md) |
| 一键部署脚本（C1.13） | `scripts/deploy-customer.sh`（PR 待发布） |
| 离线包打包（C1.14） | `scripts/build-offline-bundle.sh`（PR 待发布） |
| LangFuse 官方文档 | https://langfuse.com/self-hosting |

**故障升级路径**：本文档无法解决的问题 → 联系图灵科技工程负责人 #25（联系方式见 on-call runbook 附录 A）。
