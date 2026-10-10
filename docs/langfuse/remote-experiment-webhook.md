# Remote Experiment Webhook 对接

`POST /v1/webhooks/langfuse` 接收平台触发，校验签名、数据集名称和执行范围后启动内部评测进程。
评测复用 `harness.http_evaluation.run_case` 与本地 Python 评分，固定请求已启动的
`http://127.0.0.1:8000`，不启动 app、不修改后端配置、不连接数据库准备消息。

## 配置

| 配置 | 用途 |
|---|---|
| `ENABLE_LANGFUSE_WEBHOOK=true` | 开启端点 |
| `LANGFUSE_WEBHOOK_SECRET` | 验证平台签名 |
| `ENABLE_LANGFUSE=true` 与 `LANGFUSE_*` 项目凭据 | SDK Experiment 记录与结果上传 |
| `EVAL_USER_ID`、`EVAL_ROOM_ID` | 授权测试账号与群 |

app 的后端地址须预先配置为本次评测使用的 mock 或 Java。
业务写入须使用授权身份与数据，配置凭据不替代业务授权。

平台 Dataset 页面配置 `Custom Experiment` 触发地址并启用请求签名。
Docker 内访问宿主机使用 `host.docker.internal`，不能使用容器自身的 localhost。
平台 URL 校验依部署版本的 SSRF 策略执行；反向代理可通过 80 或 443 接收 webhook，
再转发至本地 8000 app。内部评测仍访问 8000，不将 app 改为其他端口。
私网访问白名单配置见 [自托管说明](./self-hosted-deployment.md)。

## 数据集与执行范围

`datasetName` 对应 git 中的黄金文件，如 `biz/swap_prod`、`intent/swap_instrument`。
内部适配器读取平台 Dataset，将稳定用例 ID 绑定到本地黄金用例。
平台输入与期望必须与 git 投影一致；缺项、重复项、不一致或未找到指定 ID 均报错，执行前须完成数据同步。
平台内容不覆盖 git 黄金集。

Default config 支持以下字段，其他字段返回 400：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `ids` | 字符串数组 | 全部 | 黄金用例 ID 或平台 Item ID |
| `limit` | 正整数 | 不限 | 执行选中范围的前 N 条 |
| `concurrency` | 正整数 | 1 | 业务集仅允许 1；意图集可指定并发 |

```json
{"ids": ["ai_trade_assist_prod_swap_order_case_1"], "concurrency": 1}
```

## 执行与结果

内部 `harness.remote_experiment` 是平台触发适配器，不是另一套评测工具或评分标准。
它复用本地 HTTP 执行与评分，将完整 report 作为 SDK Experiment 输出，并将已有结论转为 Score。
意图结论使用 `det_intent_pass`，有效子评分使用 `det_intent_match_pass`、`det_instrument_match_pass`；
业务结论使用 `det_business_pass`。SKIP 不产生通过分数，不调用 Judge，不等待平台 JS Rule。

| 状态码 | 含义 |
|---|---|
| 202 | 已启动评测进程，不代表实验成功 |
| 400 | 请求、范围或数据集名称无效 |
| 401 | 签名校验失败 |
| 404 | webhook 未开启 |
| 409 | 同一数据集已有实验运行 |
| 503 | 签名密钥、Langfuse 或授权身份配置未就绪 |

日志与逐条报告写入仓库外：Windows 为系统临时目录的 `aigc-langgraph-tmp/harness/`，
Linux 为 `/opt/work-file/code-tmp/aigc-langgraph-tmp/harness/`。
启动响应提供日志路径，实验报告路径在日志中输出。
本地 PASS 与平台上传状态分别核查，平台入库需检查 Experiment、Observation 与 Score。

## Windows 容器代理

分支保留的 [Compose 补充文件](../../infra/langfuse/docker-compose.eval-proxy.yml) 和
[Nginx 配置](../../infra/langfuse/eval-proxy.nginx.conf) 可供 Windows 的 80 端口被占用时使用。
代理只监听容器内的 80 端口，不向 Windows 发布端口；Langfuse 使用
`http://eval-proxy/v1/webhooks/langfuse`，代理转发到宿主机 8000，与上述内部评测入口一致。

启用时保留当前部署使用的全部 Compose override，再追加补充文件；该文件将 web 的
`LANGFUSE_WEBHOOK_WHITELISTED_HOST` 覆盖为 `eval-proxy`。先检查 Compose 配置与
`nginx -t`，再仅重建代理和 web 服务，不升级 Langfuse 镜像。请求正文和签名头透传，
密钥仍只通过应用配置加载。无签名空请求应返回 401；202 只证明实验已受理。
本次 PR 准备未启动或修改实际 Docker 部署，代理运行验收仍待执行。
