# 故障排查

## 启动类问题

### Q: AIOMySQLSaver.setup() 报 "Access denied"
**原因**：MySQL 用户对 `otc_agent_checkpoint` 库权限不够。
**解决**：
```bash
docker compose exec mysql mysql -uroot -prootpassword -e \
  "GRANT ALL PRIVILEGES ON otc_agent_checkpoint.* TO 'otc_agent'@'%'; FLUSH PRIVILEGES;"
```

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

### Q: Qwen API 不通
**原因**：`QWEN_API_BASE` 配置错 / 内网访问受限。
**解决**：
```bash
curl $QWEN_API_BASE/models -H "Authorization: Bearer $QWEN_API_KEY"
# 应返回模型列表
```

## 运行时问题

### Q: 消息识别为 unknown
**排查**：
1. 查 `trace` 里 `route_product` 的 decision 字段
2. 对照 `app/nodes/route.py` 里的关键词列表
3. 若关键词确实没覆盖，提 PR 加关键词

### Q: 意图识别错了（swap 识别成 option）
**排查**：
1. 查 `raw_content` 里的关键词优先级
2. 路由规则是"关键词优先"，若同时命中，第一个赢
3. `app/nodes/route.py` 的规则顺序：
   - 平仓单号正则 > 附件 > 关键词（平仓 > 互换 > 期权）

### Q: 标的识别返回空
**排查**：
1. goats 库不通？在 `ticker_tools.py::search_goats` 加日志
2. LLM 自行跳过了 search_goats？看 LangSmith trace
3. Agent 循环超限？设 `recursion_limit=25`

### Q: LLM 输出 JSON 解析失败
**可能原因**：`with_structured_output` 的 Pydantic 校验失败。
**定位**：看 `state['error']` 或 `trace` 里 error 节点的详情。
**修复**：
- Qwen 对 function calling 的支持不稳定，切 `method="json_mode"` 试试
- 或者 Pydantic 模型字段约束过严，适当放宽

### Q: 后端 API 调用 500
**定位**：
1. `trace` 里看 `call_*_api` 节点的 output_preview
2. `tenacity` 已重试 3 次，若仍失败，是后端问题
3. 检查 payload 字段名是否 camelCase（后端约定）

### Q: 会话历史错乱（返回别的客户的订单）
**原因**：thread_id 用错了。
**确认**：`thread_id` 必须 = `conversation_id`（不是 room_id / user_id）。
检查：`app/api/routes.py` 里的 `config = {"configurable": {"thread_id": req.conversation_id}}`。

## 测试类问题

### Q: E2E 测试失败，mock 的后端方法没被调用
**原因**：Python mock 陷阱。要 patch "使用点"，不是定义处。
**解决**：在 `tests/test_e2e.py::mock_backend` fixture 里，必须 patch：
- `app.tools.otc_backend.OtcBackendClient`（定义处）
- `app.subgraphs.swap.OtcBackendClient`（使用点）
- `app.subgraphs.option.OtcBackendClient`（使用点）
- `app.subgraphs.close.OtcBackendClient`（使用点）

### Q: 测试依赖 langgraph 没安装就报错
**解决**：
```bash
pip install -e ".[dev]"
```
或者在没装 langgraph 的环境下，相关测试会自动 skip（通过 `@pytest.mark.skipif`）。

### Q: pytest 跑一半卡住
**原因**：某个测试真的调用了外部 LLM/HTTP。
**解决**：
1. 找卡住的测试：`pytest --timeout=30`
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

### Q: P95 延迟 > 10s
**排查**：
1. 看 LangSmith 或 trace，哪个节点慢
2. 大概率是 `extract_place_order`（用 133K 字符提示词）
3. 优化方向：
   - 路由阶段用 Haiku 蒸馏小模型（1s 内）
   - 只在真实需要时才用 thinking 模型
   - 并行化 ingest 已经做了

### Q: MySQL 连接数爆了
**原因**：每个请求建新连接。
**检查**：AIOMySQLSaver 默认连接池 10。生产调大：
```python
# 在 app/checkpointer/factory.py
# 参考 langgraph-checkpoint-mysql 的 Pool 参数
```

### Q: Qwen API 速率限制
**缓解**：
- 提高并发请求复用：httpx AsyncClient 复用
- 添加 tenacity 的 rate_limit 装饰
- 接备用模型（Claude / DeepSeek）做 fallback

## 生产事故响应

### 大面积解析失败
1. **立即**：`USE_LANGGRAPH=false` 切回 Dify
2. 看最近 1h `message_log` 表的 error 分布
3. 看 LangSmith 定位是哪个节点批量失败
4. 热修复走 hotfix 分支，跑 golden set → 快速发布

### Shadow 双跑一致率骤降
1. 看最近 24h `shadow_compare` 表的 is_equal=0 分布
2. 按 diff_detail 字段分类
3. 若 > 5% 不一致：暂停灰度，调 dify-reviewer

### 某个客户反馈订单识别错了
1. 从 `message_log` 拉该客户该时段消息
2. 在本地重现：`curl /v1/message` 发同样 payload
3. 看 trace 定位错误节点
4. 补 golden case 防止回归
