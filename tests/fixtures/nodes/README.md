# 节点级回归 fixture

该目录由本地自动化测试工作台的“节点标注”功能维护。目录结构为：

```text
tests/fixtures/nodes/<product_type>/<node_name>.jsonl
```

每行保存一条人工确认的节点输入和期望输出，并记录来源 case、Langfuse trace / observation、
标注人和更新时间。工作台持久化已知节点声明的稳定字段，或自动发现节点的公共输出字段，
不保存整份 AgentState。

运行全部可回放节点 fixture：

```bash
python -m harness node-run --data tests/fixtures/nodes

# 离线试跑：仅 mock LLM / Ticker 等外部依赖，仍执行真实节点逻辑
python -m harness node-run \
  --data tests/fixtures/nodes/swap/swap_place_order.jsonl \
  --mock
```

带后端写副作用的节点可以保存人工标注，但不会被 `node-run` 执行；批量运行时会显示
`SKIP`，不计入失败。

只输出动态 trace、私有中间态或空对象的节点自动标记为“仅查看”，不生成没有稳定断言价值的 fixture。
未显式声明回放契约的自动发现节点一律写为 `replay.enabled=false`。

保存前会递归检查输入和期望输出；发现 API Key、Secret、Cookie、Authorization、
Bearer Token 等敏感信息时将拒绝落盘。为保证回放语义真实，系统不会用脱敏占位符
静默改写节点输入。
