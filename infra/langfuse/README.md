# LangFuse self-hosted

Harness 的后台服务，承载 trace / dataset / eval / annotation 四件套。详见 [ADR 0014](../../docs/adr/0014-langfuse-as-harness-backend.md)。

## 启动

```bash
# 1. 准备 .env（首次）
cp infra/langfuse/.env.example infra/langfuse/.env

# 2. 生成 3 个必填密钥
echo "SALT=$(openssl rand -base64 32)" >> infra/langfuse/.env
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> infra/langfuse/.env
echo "NEXTAUTH_SECRET=$(openssl rand -base64 32)" >> infra/langfuse/.env

# 3. 启动
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d

# 4. 浏览器访问
open http://localhost:3000
```

首次进入 Web UI 后，注册账号 → 创建组织 → 创建项目 → 获取 API Key。

## API Key 注入到应用

把生成的 API Key 写到 `.env`（或 shell export）：

```bash
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
ENABLE_LANGFUSE=true
```

应用内通过 `app.config.get_settings()` 读取（ADR 0014 D8）。

## 关停 / 清理

```bash
# 关停（保留数据）
docker compose -f infra/langfuse/docker-compose.yml down

# 关停并删数据（谨慎）
docker compose -f infra/langfuse/docker-compose.yml down -v
```

## 部署架构

```text
langfuse-web (3000)        ← UI + REST API
langfuse-worker (3030)     ← 异步 ingestion
langfuse-postgres (5432)   ← 元数据
langfuse-clickhouse (8123) ← trace 时序
langfuse-redis (6379)      ← 队列与缓存
langfuse-minio (9090)      ← S3 兼容存储（trace 大块归档）
```

LangFuse v3 起强制要求 ClickHouse + Redis + S3 存储，参考 [LangFuse 自托管文档](https://langfuse.com/self-hosting)。

## 数据保留策略（ADR 0014 D6）

| 类型 | 保留期 | 备注 |
|------|--------|------|
| Trace | 90 天 | 定期清理 ClickHouse 旧表 |
| Dataset | 永久 | 真理来源 |
| Score | 永久 | 评估趋势分析 |
| Annotation | 永久 | 业务方稀缺资产 |
