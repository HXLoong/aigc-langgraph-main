# /set-intent 恢复验证记录

日期：2026-09-07。契约见 [Java 后端 §6](api-contracts/java-backend.md#6-消息会话与意图持久化set-intent)。

## TDD 与覆盖范围

- 首个 HTTP 红测：首轮传空 `conversation_id`，正常返回时消息写回次数实际为 0，断言失败；接入节点与启动注入后转绿。
- HTTP 4xx、永久 5xx、业务非零码：先复现错误返回 HTTP 200，再实现 502 和脱敏文案，失败 trace 仍交给 `persist`。
- 客户端重试红测：超时、连接失败及 5xx 先直接失败，再实现 100ms 间隔的一次重试。
- 缺失或无效 `code`、其他传输错误：先复现误判成功或原始异常外泄，再实现严格成功判定与错误脱敏。
- 新增 36 个测试全部通过：真实 HTTP 入口与 `MockTransport` 请求体一致性、后续轮次复用 ID、三个业务分支及 unknown/fallback、`/operate` 顺序与整数消息 ID、等待写回确认、鉴权与 GOATS 签名、dry-run 下仍写元数据、失败后下一轮恢复、直接构图默认不写消息表。

## 原 `/set-intent` 恢复阶段回归结果

以下保留该阶段的历史结果；会话续接与纯 UUID 规则的最终结果见文末。

| 检查 | 结果 |
|------|------|
| 新增测试 + persist / API / smoke / cascade / checkpointer | 86 passed，1 个已知 UUID 基线失败 |
| `pytest tests/ -q --tb=short` | 1072 passed，15 skipped，1 个已知 UUID 基线失败，29 warnings |
| `ruff check app/ tests/` | 173 个已有诊断；修改前后诊断一致，新增 0 |
| `mypy app/` | 154 个已有诊断；修改前后诊断一致，新增 0 |
| 新增客户端、节点与测试文件的 Ruff 检查 | 通过 |
| `git diff --check` | 通过 |

全量测试沿用仓库默认排除 `tests/api` 的配置，未对真实 Java 消息表做写入验证。
Windows 测试进程使用 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，并关闭 Langfuse 发送
（`ENABLE_LANGFUSE=false`、`LANGFUSE_TRACING_ENABLED=false`）。首次仅设置输出编码时出现的
4 个子进程编码失败，在统一 UTF-8 后消失；未为此修改应用或已有测试。

静态检查使用独立临时源码副本作基线：保留任务开始前的未提交修改，仅撤除本任务新增文件与代码，
比较忽略行号位移后的诊断及数量。没有修复无关的已有 Ruff / mypy 问题。

## 会话续接与询价补参续修（2026-09-07）

按本轮明确规则，所有兼容位置均为空时生成纯 UUID，既有非空 ID 原样使用。
此前 `test_first_turn_generates_conversation_id_and_followup_reuses_it` 的括号/反斜杠包装断言已被纯 UUID 断言替代；
`eval_golden.py`、`langfuse_eval.py` 及对应测试同步更新。保留既有 `/set-intent` 实现与失败处理。

### 先失败、再修复

- `pytest tests/api_wire/test_api.py -q --tb=short`：先得到 **15 failed / 25 passed**，复现顶层 ID 被忽略、非空 ID 被裁剪及空别名冲突；修复统一解析后通过。
- `pytest tests/subgraphs/option/test_intent.py -q --tb=short`：先得到 **7 failed / 16 passed**，复现卡片关键词将 `new_inquiry` 强制改成下单；删除后处理后 **23 passed**。
- 两轮 HTTP 回归先发现 checkpoint 历史为空：已有 `record_history` 节点未接主图；接入后进一步复现 `OptionInquiryItem` 丢 `orderId`、`OptionOrderItem` 丢 `tenor`，随后补齐可选字段。
- 历史接入后，第二轮旧历史被业务子图完整输出重复累加；新增三类业务分支回归先 **3 failed**，再由主图过滤子图回传的旧历史，仅在每轮结束统一追加当前消息，连续三轮验证通过。
- 两个评估入口的纯 UUID 回归先 **2 failed / 2 passed**，移除生成值包装后 **4 passed**。

### 最终检查

| 检查 | 结果 |
|------|------|
| 询价续接 + option 全子图 + HTTP API + `/set-intent` + 多轮 state/history | **174 passed** |
| `pytest tests/ -q --tb=short`（仓库默认配置） | **1127 passed，15 skipped，29 warnings**，107.16 秒 |
| `ruff check app/ tests/` | **173 条既有诊断，新增 0** |
| `mypy app/ --no-incremental` | **154 条既有诊断，新增 0** |
| 入口/意图节点及本轮相关测试的定向 Ruff | 通过 |
| ADR 引用检查、`git diff --check` | 通过 |

静态诊断按文件、诊断类型和消息比较（忽略行号位移），与本轮开始前保留的
`set-intent-current-ruff.log` / `set-intent-current-mypy.log` 基线完全一致。

两轮集成回归使用真实 FastAPI、主图、子图、参数模型和 HTTP 客户端，
通过 `InMemorySaver` 代替 MySQL checkpoint，外部 LLM、Java HTTP 与数据库使用替身。
覆盖纯 UUID、Java 顶层 ID、两种 inputs 别名、相同值复用与不透明字符串保真；
实际 HTTP 请求体中的原 `Q-...` 单号与新增 `1M` 同传，其余缺省字段不发送，交后端合并。
同时检查次轮 LLM 收到首轮原话/回复、历史每轮只追加一次、卡片含首尾空格和换行时仍原样返回。
未运行真实 Java / LLM 联调，未执行数据库迁移或部署。
