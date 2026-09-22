# Harness（评测台）

基于 `tests/fixtures/categories/` 的 HTTP 回归评测台：经本地 `/v1/workflows/run` 驱动 LangGraph，与 `app/` 解耦。
设计见 ADR 0002 / ADR 0014。模块职责：

- `cli.py` — `python -m harness <doctor|run|node-run>` 入口 + 报告渲染
- `golden.py` — categories 两种方言的加载与归一化
- `multi_turn.py` — 多轮 case 的 HTTP 执行（quote 引用 / 早停 / at_bot 透传）
- `differ.py` — 字段级 diff + 文本 / 结构化断言
- `langfuse_client.py` / `token_tracker.py` / `case_generator/`
- `node_annotations.py` / `node_registry.py` — 从 Langfuse 动态发现业务节点；注册表只补充已知节点的稳定字段与安全回放契约，不限制节点数量
- `node_mocks.py` — 节点回归的显式外部依赖 mock（当前试点：`swap_place_order`）
- `node_fixtures.py` / `node_runner.py` — 保存并执行无写副作用的节点级 fixture
- `report_history.py` — 本地历史 JSON 报告的只读索引

用法：

```bash
python -m harness doctor          # 环境体检（/health /ready）
python -m harness run --help      # 跑 fixture；--backend real|mock|dry-run、--checkpoint none|mysql
python -m harness node-run --data tests/fixtures/nodes  # 单节点回归
python -m harness node-run --data tests/fixtures/nodes/swap/swap_place_order.jsonl --mock
# 调已启动后端的受保护接口（密钥只通过环境变量传入）
NODE_RUN_API_KEY='<key>' python -m harness node-run --transport http \
  --base-url http://127.0.0.1:8000 --data tests/fixtures/nodes
```

带写副作用的节点 fixture 只用于留存人工标注，批量回归时显示 `SKIP`，不会调用节点，
也不会计入失败。
自动发现但尚未声明回放契约的新节点也会安全跳过。
HTTP 模式会依次调用 `/v1/nodes/prepare` 和 `/v1/nodes/run`，并复用相同的字段级
diff 与 JSON 报告；HTTP 模式不支持 `--mock`。

LLM Judge 评估主入口是 `scripts/langfuse/langfuse_eval.py`（见根 CLAUDE.md「关键命令」）。
