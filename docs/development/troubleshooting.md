# 故障排查（开发期 Q&A）

> **生产故障**请走结构化 SOP：[`docs/operations/troubleshooting-sop.md`](../operations/troubleshooting-sop.md)
> **值班响应**请走：[`docs/operations/on-call-runbook.md`](../operations/on-call-runbook.md)
> 本文档是**开发期通用 Q&A**——快速查"我遇到这个错误怎么办"。

## 启动类问题

### Q: 启动报 checkpoint 表缺失或 "Access denied"
**原因**：Java 数据库尚未执行 `sql/init.sql`，或 `MYSQL_URI` 的账号对 `langgraph_` 前缀表没有读写权限。应用启动只做只读校验，不会自动建表（ADR 0009）。
**解决**：由 DBA 在 `MYSQL_URI` 指向的数据库执行一次 `sql/init.sql`，并给该账号授予 `langgraph_*` 表的 SELECT / INSERT / UPDATE / DELETE 权限。

### Q: 启动时报 "ModuleNotFoundError: No module named 'langgraph.checkpoint.mysql'"
**原因**：未装 `langgraph-checkpoint-mysql`。
**解决**：
```bash
pip install "langgraph-checkpoint-mysql[aiomysql]"
# 或重新走一遍：pip install -e ".[dev]"
```

### Q: MySQL 版本是 9.6+，AIOMySQLSaver 报错
**原因**：MySQL 9.6.0 废弃了生成列的 MD5 函数。
**解决**：降级到 8.0.x 或 9.5.x。测试可用 `InMemorySaver`。

### Q: LLM API 不通
**原因**：`QWEN_API_BASE` 配置错 / 内网访问受限（变量沿用 `QWEN_*` 前缀，实际模型为 DeepSeek-V4-pro，ADR 0020）。
**解决**：
```bash
curl $QWEN_API_BASE/models -H "Authorization: Bearer $QWEN_API_KEY"
# 应返回模型列表
```

## 运行时问题

### Q: 消息识别为 unknown
**排查**：
1. 查 `trace` 里 `intent_route` 的 decision 字段
2. 对照 `app/nodes/route_rules.py` 里的关键词 / 正则列表
3. 若关键词确实没覆盖，提 PR 加关键词

### Q: 意图识别错了（swap 识别成 option）
**排查**：
1. 查 `raw_content` 里的关键词优先级
2. 路由规则是"关键词优先"，若同时命中，第一个赢
3. `app/nodes/route_rules.py` 的规则顺序：
   - 平仓单号正则 > 附件 > 关键词（平仓 > 互换 > 期权）

### Q: 标的识别结果不对
标的识别归 Java 后端（ADR 0025），LangGraph 只传原文。
**排查**：
1. trace 里看提交给后端的 `placeOrderWindCode` / `stockCode` 是否是用户原文
2. 原文正确 → 查 Java 标的工具日志；原文提取错 → 查子图 extract 节点与提示词
3. HTTP 输出的 `tickers` 恒为空列表，不代表零命中

### Q: LLM 结构化输出校验失败
**可能原因**：`with_structured_output` 的 Pydantic 校验失败，或候选缺少证据（ADR 0027）。
**定位**：看 `state['error']` 或 `trace` 里 error 节点的详情。
**修复**：先补失败用例，再改提示词或输出模型的 `Field(description=)`；不要手工解析 JSON。

### Q: 后端 API 调用 500
**定位**：
1. `trace` 里看对应 backend 节点的 `api_code` / `api_result`
2. 写类接口**不会**自动重试（防重复下单）；只读接口经 `RetryPolicy` 最多 2 次尝试
3. 检查 payload 字段名是否与 Java DTO 一致（camelCase）
4. 用户看到的是"交易指令服务暂不可用"，原始 `api_code/api_result` 保留在审计表

### Q: 会话历史错乱（返回别的客户的订单）
**原因**：thread_id 用错了。
**确认**：`thread_id` 必须 = `conversation_id`（不是 room_id / user_id），见 `app/api/routes.py`。

## 测试类问题

### Q: E2E 测试失败，mock 的后端方法没被调用
**原因**：Python mock 陷阱。要 patch "使用点"，不是定义处。
**解决**：按使用点 monkeypatch（先例：`tests/test_inquiry_continuation.py`），例如：
- `app.subgraphs.option.backend.OptionClientHttpx` / `app.subgraphs.close.backend.OptionClientHttpx`（option 与 close 共用同一类，两处都要 patch）
- `app.subgraphs.swap.backend.SwapClientHttpx`

### Q: 测试依赖 langgraph 没安装就报错
**解决**：
```bash
pip install -e ".[dev]"
```

### Q: pytest 跑一半卡住
**原因**：某个测试真的调用了外部 LLM/HTTP。
**解决**：
1. 找卡住的测试：`python -m pytest -x -v` 看最后一条输出
2. 加 mock

## Claude Code 相关

### Q: Claude Code 启动时没加载 CLAUDE.md
**检查**：
1. 当前目录是否在项目根（`pwd` 应看到 `.../otc-agent`）
2. `CLAUDE.md` 是否真的存在：`ls CLAUDE.md`
3. 在 Claude Code 里跑 `/memory` 看加载的文件

### Q: 某个 subagent 没被调用
**原因**：subagent 的 `description` 字段需要清晰描述何时用。
**解决**：改 `.claude/agents/<agent>.md` 的 frontmatter description。
或者显式召唤："use <agent_name> to do xxx"。

### Q: 每次跑 pytest 都问我权限
**解决**：在 `.claude/settings.json` 的 `permissions.allow` 里已经加了 `Bash(pytest:*)`。
若仍问，检查你的全局 `~/.claude/settings.json` 是否有 deny 规则覆盖。

### Q: Claude 改了代码破坏了测试
**解决**：
1. `/rewind` 回到上一步
2. 或 `git diff` + `git checkout .` 回滚

## 性能问题

### Q: P95 延迟偏高
**排查**：
1. 看 LangFuse trace 或 `/metrics` 的节点延迟直方图，定位慢节点
2. 通常是提示词过长的抽取节点或后端往返；当前基线见 ADR 0019
3. 不要通过跳过校验或合并写路径来提速

### Q: MySQL 连接数爆了
**检查**：checkpointer 使用连接池（`CHECKPOINT_POOL_MAXSIZE` 默认 10，`CHECKPOINT_POOL_RECYCLE_SECONDS` 须小于 `wait_timeout`），按实例数核算总连接数。

### Q: LLM API 速率限制
**缓解**：降低评测并发（`--concurrency`）；生产侧联系模型网关提升配额。不要在 client 里自写重试（重试统一由 `RetryPolicy` 管理）。

## 生产事故响应

生产故障按 [`docs/operations/troubleshooting-sop.md`](../operations/troubleshooting-sop.md) 与 [`docs/operations/on-call-runbook.md`](../operations/on-call-runbook.md) 执行；紧急回滚见 runbook §7。

### 某个客户反馈订单识别错了
1. 从 `langgraph_message_log` / `langgraph_node_trace` 拉该客户该时段消息与节点轨迹
2. 本地用同样 payload 请求 `POST /v1/workflows/run` 重现
3. 看 trace 定位错误节点
4. 先在 `tests/fixtures/categories/` 补 case，再按 TDD 修复
