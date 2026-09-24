# 外部 API 契约

本目录记录 LangGraph 所调用外部系统的**真实**接口契约，是 `app/tools/` 下 Pydantic 模型与 Client Protocol 的事实依据。
外部契约变更时同步修改对应文档。

| 文档 | 覆盖 |
|---|---|
| [java-backend.md](./java-backend.md) | Java 后端业务 API：期权 `/financial-orders/operate`、互换 `/swap-order/operate`、标的查询等 |

标的识别的职责边界见 [../architecture/backend-instrument-boundary.md](../architecture/backend-instrument-boundary.md)。
