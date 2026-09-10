fix(option): 修复询价标的绑定并清理回归检查阻塞项

## 概述

修复期权询价中的标的身份绑定、期限候选过滤及 GOATS 快速询价响应解析和参数透传，并清理回归检查中的全部阻塞项。输入 `600519.SH，欧式看涨,1M/2M,80%` 时，合法候选 `600519.SH` 和 `600519` 均可进入标的查询，期限和比例被过滤，最终订单绑定经 GOATS 校验的标的。

## 变更内容

- 调整新增标的测试，验证期限和比例不进入推断及 GOATS 查询、最终标的正确且 `from_goats=True`。
- 将 16 个需要写回的测试切换到 staging，继续 mock LLM、HTTP 和数据库等外部边界；新增 development 环境不创建消息写回客户端的验证。
- 更新两个 smoke 测试：保留旧历史并准确追加本轮用户消息和回复；逐轮核对包含 `persist_intent` 的完整 trace 路径，验证 trace 隔离与历史累积。
- 清理原有 145 项 Ruff 问题。协议模型的 Python 字段使用 snake_case，Pydantic alias 保留 Java JSON、LLM schema 和 checkpoint 的 camelCase 键，包括 `sourceKeywords` 和 `participateRate`。共享 `WireModel` 默认按 alias 导出，兼容现有 Pydantic 2.8+ 依赖；调用点同步调整。
- 增加旧 checkpoint 重建与再次序列化、数值数组归一化和 State 参数显式字段保留测试。
- 从 Git 提交 `68e11d5519e4d0e90546f4c4436293e9187b793b` 恢复三个缺失基准文件。期权 QA 131 条、业务种子 287 条与历史 blob 逐字节一致；unified 原有 325 条完整保留，再同步当前主集与规则锚点，共 921 条。
- 恢复独立的 `g001`–`g030` 规则锚点，修正一致性脚本对主集旧编号的假设；保持当前 535 条主集内容和编号不变。检查文件非空、编号唯一、原始输入覆盖和锚点完整性；同步脚本保留多轮消息、预期及来源，重复运行不增加数据。
- 当前分支另包含 MySQL 表名大小写配置和测试报告忽略规则调整。

## 验证

2026-09-09，设置 `PYTHONUTF8=1`、`ENABLE_LANGFUSE=false` 后验证：

| 检查 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/ -v -ra` | **1363 passed，15 skipped，0 failed，0 errors**；77.48 秒。`-ra` 仅用于列出跳过原因 |
| `.venv/Scripts/python.exe -m ruff check app/ tests/` | **All checks passed，零问题** |
| `.venv/Scripts/python.exe scripts/check_fixture_consistency.py` | **通过**；6 个 fixture、1938 条累计记录（非去重） |
| fixture 同步幂等性 | 再次运行 `scripts/merge_golden.py` 后，unified 文件 SHA-256 不变 |
| 数据恢复核验 | 两个快照与 Git blob 逐字节一致，unified 原始 325 条内容与编号不变，当前主集不变 |

跳过原因与修复前一致，未新增 skip：

- 14 个标的 fixture：`tk007`–`tk017`、`tk019`、`tk020`、`tk034` 没有 `expected.winner`，原有测试按条件跳过 winner 检查。
- 1 个回滚脚本测试：Windows 不支持 chmod，原有平台条件跳过该检查。
- `tests/api` 按仓库既有 pytest 配置排除，依赖真实后端与 VPN；未改变该配置。上述测试结果不代表真实交易后端或真实 LLM 的联调结果。

## 检查清单

- [x] pytest 无失败或错误；所有跳过项已说明，无新增 skip。
- [x] Ruff 零问题，未降低规则或新增命名豁免。
- [x] fixture 已从 Git 恢复，来源和同步规则记录于 `tests/fixtures/README.md`。
- [x] State 初始化已核对通过；未新增 AgentState 顶层字段，旧 TickerCandidate checkpoint 默认来源词为空并通过重建测试。
- [x] 提示词加载：不适用，未变。
- [x] 新增节点/意图：不适用，未变。
- [x] 依赖变更：不适用，未变。
- [x] secret 检查：从分支与 upstream/main 的 merge-base `6017a390ba176dbf1feffcb23094f5e429b097d3` 起，检查分支及工作区新增内容、恢复数据和新增文件；常见凭据模式、私钥和本地已配置凭据比对未发现 secret。原有未跟踪数据库 dump 不属于本次交付。
- [x] 中文变更说明已准备。

## 关联

数据恢复来源：提交 `68e11d5519e4d0e90546f4c4436293e9187b793b`（删除提交 `e4c132a` 的父提交）。

本文件为待同步的 PR 描述。已查询 origin `HXLoong/aigc-langgraph-main` 和 upstream `GZTL-AI/aigc-langgraph`，未找到 feature-hxl 对应的开放 PR；获得目标 PR 链接后同步远端描述。
