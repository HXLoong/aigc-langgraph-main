# LangFuse self-hosted

Harness 的后台服务，承载 trace / dataset / eval / annotation 四件套。详见 [ADR 0014](../../docs/adr/0014-langfuse-as-harness-backend.md)。

## 启动

```bash
# 1. 准备 .env（首次）
cp infra/langfuse/.env.example infra/langfuse/.env

# 2. 编辑 infra/langfuse/.env，填入 3 个必填密钥（模板里已有空的 SALT= / ENCRYPTION_KEY= / NEXTAUTH_SECRET=）
openssl rand -base64 32   # → SALT
openssl rand -hex 32      # → ENCRYPTION_KEY
openssl rand -base64 32   # → NEXTAUTH_SECRET

# 3. 启动
docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d

# 4. 浏览器访问
open http://localhost:3000
```

首次进入 Web UI 后，注册账号 → 创建组织 → 创建项目 → 获取 API Key。

## API Key 注入到应用

把生成的 API Key 写到仓库根目录 `.env`（或 shell export）：

```bash
LANGFUSE_BASE_URL=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
ENABLE_LANGFUSE=true
```

应用内通过 `app.config.get_settings()` 读取（ADR 0014 D5）。

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

## 可选：Windows 本地实验回调代理

Windows 的 80 端口已被占用时，可用
[docker-compose.eval-proxy.yml](./docker-compose.eval-proxy.yml) 加入 Nginx 容器。
Langfuse 访问代理容器的 80 端口，代理再访问本机应用的 8000 端口，不占用 Windows 的 80 端口。
只转发 `/v1/webhooks/langfuse`，配置见 [eval-proxy.nginx.conf](./eval-proxy.nginx.conf)。

按 [Remote Experiment Webhook 对接](../../docs/langfuse/remote-experiment-webhook.md) 的「Windows 容器代理」一节
准备签名、保留原有 Compose override、启动代理并验证。该可选文件覆盖 web 容器的回调白名单；
启用后 Remote Experiment URL 使用代理容器名。它不修改 Langfuse 镜像版本。

## Code Evaluator dispatcher

v4 的 Code Evaluators 需要一个执行器，**不配置则功能整体关闭**（建 evaluator 返回
`412 Code evaluations are not enabled for this deployment.`）。在 `infra/langfuse/.env` 填写后重启：

```bash
LANGFUSE_CODE_EVAL_DISPATCHER=insecure-local
QUEUE_CONSUMER_CODE_EVAL_EXECUTION_QUEUE_IS_ENABLED=true
```

| Dispatcher | 用途 | 运行时支持 |
|---|---|---|
| `insecure-local` | 本地开发；在 worker 进程内用 Node 执行 | **只有 TypeScript/JavaScript** |
| `aws-lambda` | 生产自托管；派发到 Lambda 执行器 | Python + TypeScript/JavaScript |

**worker 镜像只有 Node，没有 Python 解释器**，所以 Python evaluator 在本地跑不了 —— 会返回
`412 This code evaluator language is not supported by the configured dispatcher.`。

`insecure-local` 不是安全边界（evaluator 代码能碰到 worker 的数据库、队列与凭证），只在
"所有能建 evaluator 的人都被信任"时使用；生产自托管应部署 `aws-lambda` 执行器。

云端能跑 Python 是因为云端用官方部署的 Lambda 执行器，私有化部署拿不到。
仓库的 evaluator 是纯 JS（`harness/evaluators/*.js`），在 `insecure-local` 下可执行。

## 数据保留与客户内网部署

保留策略见 [ADR 0014](../../docs/adr/0014-langfuse-as-harness-backend.md) D5；客户内网部署、备份、升级见
[docs/langfuse/self-hosted-deployment.md](../../docs/langfuse/self-hosted-deployment.md)。
