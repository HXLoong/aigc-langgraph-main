# ADR 0021 · 文本二阶段确认替代 LangGraph interrupt + checkpointer 接线

- 状态：已采纳
- 日期：2026-08-27
- 起源：2026-08-27 裁决（全量核查发现 [ADR 0006](./0006-hitl-interrupt-boundary.md) 0% 落地）
- 取代：[ADR 0006](./0006-hitl-interrupt-boundary.md) 的 interrupt 机制部分（其"写 + 资金双轴"风险象限规则仍沿用）
- 作者：图灵科技 + Tony

## 上下文

ADR 0006 决策用 `interrupt_before` 拦截写+资金类节点，但核查确认其执行载体从未存在：主图无 `interrupt_before`、生产图 `checkpointer=None`、`/v1/message/confirm` 恢复端点缺失。与此同时，**文本"确认"路径已在生产实际工作**：客户回复"确认"→ 意图分类 → `confirm_*` 意图节点执行写操作（swap/option/close 三子图均有此路由）——原设计中的"按钮故障兜底"事实上成为唯一路径，且被 M2/M3 评估验证可用。

## 决策

### 1. 文本二阶段确认为正式确认机制（interrupt 不做）

写+资金类动作（place_order / cancel / modify / place_close）的客户确认统一走**文本二阶段**：

```
客户发起 → 节点提取参数 → render 输出确认卡（文本）→ 单轮结束
客户回复"确认"→ 一级路由 + 子图 intent → confirm_* 节点 → 真正写后端
```

不实现 `interrupt_before` / 确认按钮回调端点。理由：

- 文本路径已被验证可用且被 golden 覆盖；interrupt 路径需要企微按钮回调链路 + Java 侧配合新联调面，当前引入不现实
- 二阶段语义等价：写操作同样需要客户显式二次表达，风险象限规则（ADR 0006 表）继续用于判断"哪些意图必须走二阶段"
- 单轮结束 + 新消息重新起图的模型更简单，不依赖 interrupt 的 checkpoint 恢复语义

### 2. checkpointer 接线（同批落地，修复 [ADR 0009](./0009-mysql-version-and-tdsql-compatibility.md) 严重偏离）

多轮对话状态持久化与 interrupt 无关，是**生产正确性**要求（跨进程/重启不失忆），随本 ADR 一并接线：

- 新增配置 `use_mysql_checkpointer`（`app/config.py`）：**生产必须 true**——lifespan 在 `environment=production` 且未启用时直接 fail-fast；显式启用后 AIOMySQLSaver 初始化失败同样直接抛（硬依赖，不静默降级）
- 开发/CI 默认 false：本地测试不被 MySQL 依赖绑架，避免 checkpoint 脏状态引起测试翻转；本地要验证持久化行为时在 `.env` 打开
- `.env.customer.template` 已加 `USE_MYSQL_CHECKPOINTER=true`；~~现场首启即执行 `.setup()` 建表~~ **2026-09-18 修订（[ADR 0009](./0009-mysql-version-and-tdsql-compatibility.md) 共库调整）**：建表统一走 `sql/init.sql`（`langgraph_` 前缀表、与 Java 共库），应用启动只读校验 schema、缺表 / 版本不符明确失败，不在节点或 lifespan 调用 `saver.setup()`——TDSQL 兼容性第一次真实验证的时点相应为"现场执行 `sql/init.sql` + 首启校验"，部署 checklist 须包含
- 回归测试：`tests/test_checkpointer_wiring.py`（fail-fast / 硬依赖 / 接线 / 默认关 5 用例）

## 备选方案

- **补齐 interrupt 全套**（ADR 0006 原设计）：需企微按钮回调 + Java 配合 + checkpoint 恢复语义管理，成本与风险不成比例；文本路径已可用，收益增量小。
- **checkpointer 也不接**：多轮状态继续无持久化，重启失忆 + HITL 类场景永久受限——生产不可接受。
- **checkpointer 默认全局开**：本地/CI 测试被 MySQL 绑架，同 conversation_id 的 checkpoint 残留造成测试翻转（`tests/CLAUDE.md` 根纪律）。

## 后果

- ADR 0006 标记被本 ADR 取代（风险象限表保留引用）；[ADR 0008](./0008-ticker-resolution-as-react-agent.md) c 段的 interrupt 消歧同理不做（ticker 消歧走 render 文本卡片，已是现状）。
- 现场部署 checklist 新增：执行 `sql/init.sql` 后首启校验 checkpoint 4 张 `langgraph_checkpoint*` 表通过（ADR 0009 09-18 口径）。
- 未来若业务方强烈要求按钮式确认，重开 ADR 评估 interrupt——届时 checkpointer 已就位，增量只剩端点与按钮回调。
- `confirm_*` 意图的数据集覆盖成为确认链路的唯一回归防线（范围校验见 [ADR 0027](./0027-field-evidence-contract.md) D5）。
