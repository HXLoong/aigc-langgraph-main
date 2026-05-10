# 标的识别采用 ReAct Agent 而非固定链式流程

中国 A 股标的格式规范（6 位代码 + 交易所后缀），但本系统服务的场外衍生品场景大量涉及境外标的，存在两类硬识别难题：

1. **境外期货/商品的行业俗称**：客户口头/聊天里用"伦铜"指 LME 铜期货、"布油"指 Brent 原油，无统一命名规范。
2. **跨市场的中文简称**：客户写"腾讯"代表 `00700.HK`、写"50ETF"代表 `510050.SH`，需要简称→代码映射 + 上下文消歧。

识别这些标的的步骤序列**事先不确定**：短文本可能 1 步命中字典，俗称可能需要 5 步（分词 → 候选词典 → 查 GOATS → 排序 → 推断完整代码），用户输入决定路径分支。

我们采用 **LangGraph ReAct Agent + 工具循环**（`ticker.py` + `ticker_tools.py`）作为标的识别子流程，被 swap / option / close 三个业务子图共同调用。`from_goats=True` 是 ReAct 输出的硬约束——任何最终标的必须经 GOATS 库回查确认。

## Considered Options

- **固定链式四步**（分词 → 查询 → 排序 → 输出）：覆盖 A 股没问题，但碰到俗称需要大量"是否进入下一步"的判断胶水代码，且短文本场景被迫跑全四步浪费延迟。
- **LLM 单次结构化输出**：让 LLM 直接吐 `{name, code, market}`，但俗称需要外部字典查询才能确认，单次调用无法访问字典。
- **ReAct Agent（已选）**：让 LLM 自己决定调多少次工具，路径长度按输入复杂度自适应。代价是 trace 步数和 token 浮动需要单独监测。

## Consequences

- ReAct 内部的工具调用次数必须作为独立观测指标记录到 `node_trace`（参考 ADR-0004），便于发现"某类输入持续触发超长循环"的退化场景。
- ReAct 输出必须强制走 `from_goats=True` 校验（CLAUDE.md 已列入"绝对约束"），防止 LLM 自由发挥编造代码。
- 需要为高频俗称建本地字典缓存（如"伦铜"等），减少每次都让 LLM 重新推理的成本——这是后续优化项，当前依赖提示词内置词典。
- ReAct Agent 跨子图共享，意味着任何对它的改动会同时影响 swap / option / close 三条业务线，golden set 必须覆盖三个子图的标的识别 case。

## 后续迁移澄清（与 Dify 等价性）

- **标的查询数据源**：原 V1 闭环为脱离 VPN 改成了 MySQL 直连标的池表，丢失了后端打分排序业务规则。已由 **ADR-0012** 修正为恢复走后端 HTTP API（`POST /admin-api/integration/securities-instrument/select`）。
- **推断 prompt 的动态片段**：Dify 工作流额外拉取 `swap_instrument_inference_prompt` 配置项注入 prompt，本 ADR 未涉及，由 **ADR-0013** 补齐。
- **本 ADR 描述的"ReAct Agent 收敛 31 节点"在结构层面有效**，但运行时数据获取的两个细节（数据源 + 动态 prompt）必须配合 ADR-0012 / 0013 才与 Dify 等价。
