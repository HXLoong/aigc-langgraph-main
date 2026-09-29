# Remote Experiment Webhook 对接

在 Langfuse Dataset 页面点 `Run`，直接触发本机跑一次数据集实验，结果按 Dataset / Experiment / Score
闭环回写。端点实现见 [app/api/langfuse_webhook.py](../../app/api/langfuse_webhook.py)。

本机侧只做验签、解析配置、点火；实验交给 `scripts/langfuse/langfuse_eval.py` 子进程跑。

## 一、Langfuse 侧

Dataset → `Start Experiment` → `⚡ Custom Experiment` → 填 URL 与 Default config：

![Edit remote experiment trigger：URL 与 Default config](./images/webhooks/url-config.png)

- **URL** —— `http://host.docker.internal:80/v1/webhooks/langfuse`
  - 端口只能是 **80 或 443**：Langfuse 发送前做 SSRF 校验，其它端口直接拒绝，白名单放不开
  - Langfuse 跑在容器里时用 `host.docker.internal`；容器内的 `localhost` 指容器自己
  - 这是应用直接监听本机 80 端口的接法；Windows 的 80 端口已占用时，改用 § 二 B 的容器代理及对应 URL
- **Default config** —— 默认参数，触发时用户可改，支持的键见 § 三
- **Advanced Options → Enabled** —— 暂停触发但保留配置

打开 **Sign requests**，保存后密钥只显示一次：

![Sign requests 开关与一次性密钥](./images/webhooks/sign.png)

把它复制到根目录 `.env` 的 `LANGFUSE_WEBHOOK_SECRET`。密钥丢了就关掉开关保存、再打开保存，会重新生成。

## 二、本机侧

```bash
uvicorn app.main:app --port 80        # 必须是 80 或 443
```

| 变量 | 文件 | 说明 |
|---|---|---|
| `ENABLE_LANGFUSE_WEBHOOK` | `.env` | 默认 `false`；关闭时端点返回 404 |
| `LANGFUSE_WEBHOOK_SECRET` | `.env` | Langfuse 生成的一次性密钥；为空返回 503 |
| `LANGFUSE_WEBHOOK_WHITELISTED_HOST` | `infra/langfuse/.env` | 填 `host.docker.internal`，改后需 `docker compose up -d` |

白名单那项是必需的：`host.docker.internal` 解析到私网地址，Langfuse 默认拒绝。

## 二 B：Windows + Docker Desktop 使用容器代理

适用于应用已在本机 8201 端口运行、Windows 的 80 端口被其它服务占用的情况。代理监听的是
**容器自己的 80 端口**，不向 Windows 发布端口，因此不需要停掉占用 80 端口的服务。

```text
Langfuse web → eval-proxy:80/v1/webhooks/langfuse
            → host.docker.internal:8201/v1/webhooks/langfuse → 本机应用
```

1. 确认练习使用沙箱项目。根目录 `.env` 设置 `ENABLE_LANGFUSE_WEBHOOK=true`，并把页面
   `Sign requests` 生成的密钥填入 `LANGFUSE_WEBHOOK_SECRET`，修改后重启应用。不要把密钥放进
   Nginx 配置或自定义 Headers。代理配置文件已经提供：
   [Compose 补充文件](../../infra/langfuse/docker-compose.eval-proxy.yml)、
   [Nginx 配置](../../infra/langfuse/eval-proxy.nginx.conf)。

2. 在仓库根目录打开 PowerShell，读取当前 web 容器使用的 Compose 文件列表，再追加代理文件。
   **保留原有 override**，其中可能固定了镜像版本或其它运行配置。以下命令仅读取容器标签，不输出环境变量或密钥。

   ```powershell
   $webIds = @(docker ps --filter "label=com.docker.compose.service=langfuse-web" --format '{{.ID}}')
   if ($webIds.Count -ne 1) { throw '需要恰好一个运行中的 langfuse-web 容器；请先确认当前部署。' }
   $labels = docker inspect $webIds[0] --format '{{json .Config.Labels}}' | ConvertFrom-Json
   $lf = @('compose', '--project-name', $labels.'com.docker.compose.project')
   $lf += @('--env-file', 'infra/langfuse/.env')
   $proxyFile = (Resolve-Path 'infra/langfuse/docker-compose.eval-proxy.yml').Path
   foreach ($file in ($labels.'com.docker.compose.project.config_files' -split ',')) {
       if ((Resolve-Path $file).Path -ne $proxyFile) { $lf += @('-f', $file) }
   }
   $lf += @('-f', $proxyFile)
   docker @lf config --quiet
   if ($LASTEXITCODE -ne 0) { throw 'Compose 配置校验失败，先处理报错。' }
   ```

3. 检查 Nginx 配置，再启动代理和更新 web 容器白名单。web 会短暂重建；命令不启动或重建其它依赖。
   `--pull never` 防止拉取新版本，所需镜像必须已在本机。若仅缺少 Nginx 镜像，先执行
   `docker pull nginx:1.28-alpine`；不要为了配置代理拉取或升级 Langfuse 镜像。

   ```powershell
   docker @lf run --rm --no-deps --pull never eval-proxy nginx -t
   if ($LASTEXITCODE -ne 0) { throw 'Nginx 配置校验失败，先处理报错。' }
   docker @lf up -d --no-deps --pull never eval-proxy langfuse-web
   ```

   补充文件把 web 的 `LANGFUSE_WEBHOOK_WHITELISTED_HOST` 设为 `eval-proxy`，无需另改部署 `.env`。
   它覆盖该变量原来的值；本接法让 Remote Experiment 统一经过代理。以后维护这个部署时也要带上补充文件。

4. 从 Langfuse 容器发一个不带签名、没有数据集信息的空请求，只验证代理连通性，不会运行实验。

   ```powershell
   docker @lf exec -T langfuse-web node -e "fetch('http://eval-proxy/v1/webhooks/langfuse',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(5000)}).then(r=>console.log(r.status)).catch(e=>{console.error(e.name);process.exitCode=1})"
   ```

   应输出 **401**：请求已到应用，被验签拦下，这是这一步的预期结果。`503` 表示应用未加载签名密钥；
   `404` 表示路径错误或应用开关未开启；`502` 通常表示代理访问不到本机应用，先检查 8201 服务是否在运行。

5. 页面 URL 改为 `http://eval-proxy/v1/webhooks/langfuse`，保持 `Sign requests` 开启，
   Default config 使用 § 三的参数。若更改 URL 时提示保密请求头必须重新输入，删除本接法不需要的
   自定义 Header **整行**，不要只清空 Value。保存不代表实验已运行；使用授权测试身份触发沙箱用例后，
   `202` 只表示任务已受理，是否完成仍要检查实验结果和日志。

原理与官方说明：[Compose 容器按服务名通信](https://docs.docker.com/compose/how-tos/networking/)、
[Docker Desktop 访问宿主机](https://docs.docker.com/desktop/features/networking/)、
[Nginx proxy_pass](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)。

## 三、Default config 支持的参数

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `ids` | 字符串数组 | 全部 | 只跑指定用例，填 golden case id（如 `case-023`），也接受 dataset item 的 UUID |
| `limit` | 正整数 | 不限 | 只跑前 N 条 |
| `concurrency` | 正整数 | `1` | 并发数；业务集保持 1，并发高会撞后端 dedup |

```json
{ "ids": ["case-023"], "concurrency": 1 }
```

- **`dataset` 也不用配**：用 Langfuse 传来的 `datasetName`，UI 上选的哪个就是哪个
- 其余未知键直接返回 400 —— 拼写错误当场暴露，不静默忽略
- 评分固定 `--no-judge`（[ADR 0005](../adr/0005-annotation-roles-judge-plus-business-spotcheck.md)：批量评分只用确定性断言）

## 四、响应与排查

| 状态码 | 含义 |
|---|---|
| `202` | 已受理，实验在子进程里跑 |
| `401` | 签名校验失败：密钥不一致，或 Langfuse 侧没打开 Sign requests |
| `404` | 回调路径未到应用，或 `ENABLE_LANGFUSE_WEBHOOK` 未打开 |
| `409` | 同一 dataset 已有实验在跑 |
| `503` | 开关已开但密钥为空 |

实验输出写在 `.harness-runs/langfuse-webhook-*.log`。
