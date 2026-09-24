# 测试数据集说明

## 1. 目录与职责

| 路径 | 用途 |
| --- | --- |
| `biz/*.jsonl` | 现役业务验收集（A 方言），统一验收与 `harness run` 默认只加载这里 |
| `intent/*.jsonl` | 意图集：只评一级路由与子图意图，只依赖 LLM + `mock_api`（见第 4 节） |
| `local_backend/` | 本地合成身份种子（见 `docs/testing/local-backend-seed.md`） |

已退役（无替代，勿再引用）：

- `nodes/`：节点级 fixture（ADR 0029 的 fixture 部分）；节点级调试 API（`app/node_execution`）仍在
- `unified_golden.jsonl`：B 方言历史参考集
- `categories/csv/*.csv` 与 `*.xlsx`：旧业务 fixture 的派生格式

## 2. 加载器：`harness/golden.py`（ADR 0024 D6）

`harness.golden.load_golden()` 是唯一加载器（`python -m harness run` 与
`scripts/langfuse/langfuse_eval.py --local` 共用），默认只发现 `biz/*.jsonl`，
或用 `--data` 显式选择单个文件或目录。各方言归一化为同一 `GoldenCase`：

| 方言 | 文件 | 形状 | case 级 `expected` 落点 |
| --- | --- | --- | --- |
| A | `biz/*.jsonl` | `name/caseNo + send_text + sub_scenes[]`，每轮可带独立断言 | 首轮 |
| raw | loader 兼容保留，当前无数据文件 | `id + raw_content` 单轮 | 首轮 |

B 方言（`id + conversation[{raw_content, quote_desc}]` + `expected{product_type, intent, output}`）
随 `unified_golden.jsonl` 一并退役，只作历史存档，不再参与现役加载。

一个文件只放一种方言：`biz/` 出现 `conversation` / `raw_content` 都是 lint 错误；id 跨文件唯一。

harness 的判定口径：`PASS` / `FAIL` / `REJECTED`（后端业务拒绝且无其它 diff，单独成桶，不计入 PASS 率）；
早停（节点错误 / 业务拒绝 / 技术错误）后未执行的轮次逐轮记 `runtime` 失败，多轮 case 不会因早停静默通过。
`--backend dry-run` 要求服务端 `/health` 报告 `backend_mode=dry-run`（`DRY_RUN_BACKEND=true`），否则拒绝启动；
反之 `--backend real|mock` 打在 dry-run 服务端也会被拦，避免拿假结果当回归基线。

## 3. 一致性要求与检查

- 编号跨文件唯一；一个文件只放一种方言；`$ref` 结构断言在执行前校验声明形状。
- 新增或修改业务回归记录时按文件方言写入，再跑一致性检查：

```bash
python scripts/check_fixture_consistency.py --verbose   # 现役 biz / intent；WARNING 为业务方待修数据
```

## 4. 意图集：`intent/*.jsonl`

与 `biz/` 业务集分离：只评一级路由 `product_type` 与子图 `intent`（标的子集另评标的原文），不依赖 Java / GOATS，
不写任何 `response_*` 卡片断言。`discover_fixtures()` 默认**不**纳入该目录，需显式
`langfuse_eval.py --local tests/fixtures/intent`。文件清单、冻结 / 回放两种模式、字段规则与运行方式见
[`docs/langfuse/workflow-guide.md` §8](../../docs/langfuse/workflow-guide.md)。

## 5. Excel 导出

`python scripts/convert_jsonl_to_excel.py` 默认读取 `biz/` 直属 JSONL，每个文件一张表。
`--dry-run` 只校验和统计，`--output` 可指定工作簿位置。

## 6. 结构断言引用实际卡片

业务 `expected` 可用 `$ref` 绑定本轮实际引用，避免把运行时订单号写死：

```json
{"confirm":{"orderList":[{"orderId":{"$ref":"quote.order_id"}}]}}
```

- `quote.order_id`：引用中的唯一单号；多笔时显式加 `"position": 2`，表示卡片出现顺序的第二笔，不是显示序号值。
- `quote.order_ids`：引用中去重后的完整单号列表，适用于确认范围。
- `quote.counterparty`：加 `"option": "A"`，取引用中该选项的完整对手名；重复且同名可合并，异名视为歧义。
- `quote.holding_contract`：引用的唯一合约编号，或加 `position` 选择对应持仓条目。

解析只读取实际传入本轮的完整 quote，从“例如”或“示例”起的尾部均不参与绑定，不读取本轮模型输出或未引用的历史。
缺失、越界、歧义和非法声明均记为失败；fixture lint 在执行前验证声明形状。
HTTP harness / local_eval 支持这些结构断言；Langfuse Judge 评分不替代该确定性验收。
