# LangGraph 完整重构执行记录

本次按用户确认的完整计划执行；Java 源码不变，LangGraph 仅使用本地服务。
入口保留 `/v1/workflows/run`，模型、GOATS、Langfuse 沿用现有配置。

## 基线

- 起点：`c7be6f1`，工作分支 `feature-xsc`。
- 本地 Java：`48080 → 48081`，运行目录 `aigc-vuln-fix/aigc/api`。
- 本地 MySQL：3308；LangGraph 计划使用本地 8201，禁止使用 10.49.91.229。
- categories：388 case / 407 turn / 9 多轮，无加载跳过；不并入 unified 历史集。
- 节点相关 pytest：763 passed；ruff 通过；mypy：110 errors / 41 files。
- 确认协议离线对照：50 case，39 个行为差异；零真实后端调用。

## 交付清单

- [ ] 本地 HTTP 回归基线、测试消息记录及参数级断言
- [ ] 互换 CWAIJY-957 确认协议、期权否定确认与多单范围
- [ ] 当前 Java 契约字段清单及迁移映射
- [ ] 期权、互换、平仓与共享 ticker 的确定性规则下沉
- [ ] 字段 evidence / confidence / source、来源校验与字段锁定
- [ ] 多指令分发、依赖、批量提交与逐项结果
- [ ] 并行错误合并、checkpoint 身份、ticker 异常传播与审计
- [ ] 版本化数据库迁移、完整响应幂等与不确定写入恢复
- [ ] Dify 请求响应兼容及 HTTP 录制/回放
- [ ] 日志与 Langfuse 出口脱敏
- [ ] 超时预算、取消、重试收敛及性能压测
- [ ] 全量 categories 符合期望；pytest / ruff / mypy / 文档检查通过

## 验收约定

先 RED 再修改业务代码；每个绿色里程碑本地提交并记录恢复点，不推送远端。
确认协议以当前 Java 业务手册和共享测试为准。已有测试中的旧确认语义随契约更新。
失败/拒绝/跳过分别报告，不能通过硬编码业务数据、弱化断言或改写后端回复提高通过率。
超时以 20/5/60 秒为初始目标，压测后确定预算；内部截止时间早于 Java 的 90 秒。
模型和运行时依赖暂沿用已安装版本，避免迁移时混入升级变量。

## 执行记录

第一批：确认协议、期权范围及 HTTP 边界完成。

- RED：新协议/范围测试 50 failed、11 passed；补充范围与错误模板 3 failed；HTTP 边界 5 failed。
- GREEN：全量 2190 passed、14 skipped；ruff 通过。
- 共享确认用例 50 条已纳入 `tests/fixtures/swap_confirmation_cases.json`；非法输入零后端调用。
- 存量 fixture 问题：计数校正为 388/1309；期权 CSV 移除 4 个全空列，保留全部业务单元格。
- 幂等、状态合并、schema/evidence、多指令、模型/数据库真实回归与性能工作仍待完成。


第二批：故障合并、checkpoint 身份、完整响应回放及版本化迁移完成。

- 恢复点：第一批 `70be48f`。
- RED：8 个恢复/回放失败；另补跨用户回放、过期占位及合并错误中的消息写回失败。
- GREEN：全量 2216 passed、14 skipped（启用本地 MySQL 集成测试）；ruff 通过。
- 本地 3308 / otc_agent_business 已执行 Alembic 0001_request_replay；真实数据库测试先复现缺列，再迁移验证快照跨实例恢复，测试消息已精确清理。
- 审计顺序改为 render → remember → history → persist；序列化保留 trace/history 的稳定 ID。
- 幂等存储不可用时阻止执行；过期未完成占位只标识结果待核对，不重新执行。
- 后续仍需补独立不确定结果核对流程、ticker 只读异常传播和业务层完整规范迁移。
