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

第三批：本地 HTTP 回归准备完成。

- 第二批恢复点：`47942fb`。
- 新增 scripts/local_eval.py：限定应用/数据库为 loopback，准备真实 Java 消息，按用户/群/业务查询授权对手；共用 harness 判定与 HTTP runner。
- Java 实际数据库为 otc_goats_ai_trading_dev；已通过 EVAL_JAVA_DATABASE 显式配置。本地首次误写到另一开发库的两条自建测试消息已按 ID+creator 删除。
- 本地 staging + MySQL checkpoint + 请求幂等的小样本：case-030/case-031 共 4 轮全部 PASS；完整消息写回正常。报告 .harness-runs/local-20260918-111722。
- 全量 pytest 2224 passed、15 skipped；随后新增 percentile 测试，局部 8 passed；ruff 通过。
- 后续全量基线使用固定代码工作树，避免重构中途改提示词影响同一轮评估。

第四批：字段证据基础与模型能力预检。

- 第三批恢复点：`62e7420`。
- FieldCandidate 验证 value/evidence/来源及数字边界；FieldRecord 记录来源、置信度、锁定和拒绝次数，reducer 拒绝锁定值覆盖。接入 AgentState/子图输出、ingest 重置和 checkpoint 白名单；各业务提取节点的接入仍待逐项完成。
- 388 条固定工作树运行完成，但 377 条因 QWEN_MODEL_COMPLEX=external-deepseek-ocr 不支持 Function call 失败；8 PASS/380 FAIL 是配置故障运行，不作为业务准确率或有效性能基线。
- 已将本地复杂文本模型改为与标准/意图一致的 external-deepseek-v4-pro，三种文本工厂的真实结构化能力预检通过。回归脚本现在先检查所有不同文本模型，失败即停止。
- 字段机制 11 个 RED → GREEN；全量 2237 passed、15 skipped；模型预检另做真实外部服务检查。

第五批：期权询价与互换文本提取接入证据契约。

- 第四批恢复点：`2b93551`。
- 期权询价和互换文本下单拆为候选提取 → Code 归一化 → GOATS 标的校验；模型只输出原文片段、证据和置信度。
- 确定性规则覆盖数量/金额单位、有限枚举、比例与时间；缺失值保持空。平仓比例按 Java 当前契约为 (0, 1]，快速执行的业务默认值仍由 Java 负责。
- ticker 不再把网络/结构化失败吞成零命中；模型解析及证据错误在图层有限重试，真实零命中保留原语义。
- RED → GREEN：全量 2290 passed、15 skipped；ruff 通过。原有测试中的“模型直接产生规范值”输出已改为带原文证据的候选；标的身份绑定测试直接从归一化阶段验证。
- 完整真实基线（修正模型后）：174 PASS / 214 FAIL，P50 12.207s / P95 19.116s / P99 21.640s，报告 `.harness-runs/baseline-correct-model/local-20260918-113605`。多数验收用例所需的聚鸣等对手及持仓不在当前 GOATS 授权上下文中，已请求用户提供匹配测试用户/群或补齐权限；不弱化断言。
- 当前迁移尚未覆盖互换图片/Excel、全部选择节点、完整字段锁定和多指令；新提示词仍需真实模型回归，不将单测通过视为业务验收完成。

第六批：截止时间与重试责任收敛。

- 第五批恢复点：`8dec188`。
- 请求总预算默认 60 秒（最大可配置 80 秒，早于 Java 90 秒），预留 5 秒落幂等响应；LLM 20 秒、业务工具 5 秒初始预算。异步墙钟超时覆盖整个调用，取消可穿透 safe_node。
- LLM SDK max_retries=0，图只读节点默认最多 2 次尝试；写节点仍无重试。safe_node 保留 ParamSpec / config / Runtime 注入。
- RED 10 failed → 局部 153 passed；补充真实调用墙钟取消 RED → GREEN。全量 2301 passed，唯一旧断言仍写死 30 秒，已随新默认值更新并单独复验。
- E5 审计结构、不确定结果独立核对及完整性能验收仍待后续完成。
