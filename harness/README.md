# Harness（评测台）

基于 `tests/fixtures/categories/` 的 HTTP 回归评测台：经本地 `/v1/workflows/run` 驱动 LangGraph，与 `app/` 解耦。
设计见 ADR 0002 / ADR 0014。模块职责：

- `cli.py` — `python -m harness <doctor|run>` 入口 + JSON / markdown 报告渲染
- `golden.py` — categories 两种方言的加载与归一化
- `multi_turn.py` — 多轮 case 的 HTTP 执行（quote 引用 / 早停 / at_bot 透传）
- `differ.py` — 字段级 diff + 文本 / 结构化断言
- `langfuse_client.py` / `token_tracker.py` / `case_generator/`

用法：

```bash
python -m harness doctor          # 环境体检（/health /ready）
python -m harness run --help      # 跑 fixture；--backend real|mock|dry-run、--checkpoint none|mysql
```

LLM Judge 评估主入口是 `scripts/langfuse/langfuse_eval.py`（见根 CLAUDE.md「关键命令」）。
