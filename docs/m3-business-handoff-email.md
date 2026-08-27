# 致业务方邮件草稿 · M3 Shadow 双跑接入信息

> **使用说明**：复制本文件正文（不含本说明段）发给业务方对接人。
> 仅在 M2 收尾后发送（当前已具备发送条件）。

---

**主题**：[M3 启动] 请求 Dify 接入信息 · LangGraph shadow 双跑准备

正文：

各位好，

OTC AI 工作流的 LangGraph 重构（M2）工程层已完成，准备启动 M3 阶段 —— **shadow 双跑**：
LangGraph 与现行 Dify 工作流并行接收同一份用户输入，对比两边的输出差异，
量化 LangGraph 是否能等价替代 Dify。

为完成 M3 的工具搭建，需要业务方提供以下接入信息：

## 必须项（阻塞 M3 启动）

| 项 | 用途 | 备注 |
|---|---|---|
| Dify 工作流 API URL | shadow 工具同时调 Dify + LangGraph，比对响应差异 | 完整 URL，例：`https://dify.example.com/v1/workflows/run` |
| Dify App API Key | Dify 端 Authorization 鉴权 | 工作流粒度的 key，最低读权限即可 |
| Dify 工作流输出字段定义 | 解析 Dify 返回的 `data.outputs.*` 字段（重点：`product_type` / `intent`）| 工作流截图或文档 |

## 强烈建议项（提升 shadow 数据质量）

| 项 | 用途 | 备注 |
|---|---|---|
| 24 小时真实流量样本 | shadow 跑测的输入源，比 golden case 更贴近生产 | JSONL，每行 `{message_id, raw_content, quote_content?, conversation_id}` |
| LangFuse / Dify Trace 访问权限 | 单条 diff 出现时定位差异根因 | 现有账号加 viewer 即可 |

## 后续接入清单

业务方提供上述信息后，工程团队的工作：

1. **shadow_compare.py 端到端联调**（1 天）
   - 用 10 条 case dry-run 验证 shadow 管道
   - 确认 Dify response 解析正确（`_normalize_dify` 函数）
2. **shadow 24h 跑测**（持续 24 小时）
   - 30 条 golden + 业务方真实样本
   - 退出门：主要意图 diff < 5%；下单 / 平仓 < 1%（ADR 0001 D9）
3. **diff 根因分析**（2-3 天）
   - 按 `suspected_node` 启发式定位
   - 区分：LangGraph 缺陷 / Dify 历史 bug / 双方都对（业务规则差异）
4. **金丝雀切换准备**（M4）
   - 5% → 25% → 50% → 100% 流量迁移
   - 在线 harness 监控

## 我们这边已经就绪

| 资产 | 路径 |
|---|---|
| LangGraph 工作流（24 个节点）| `app/subgraphs/{swap,option,close,ticker}/` |
| Dify 协议兼容 endpoint | `POST /v1/workflows/run` |
| shadow 工具 | `scripts/shadow_compare.py` 350 行（含 dry-run / MySQL 写入）|
| 评测台 harness（317 条 golden）| `python -m harness run` |
| 真 LLM PASS 基线 | swap 82% / option 85% / close 96%（M2 跑测报告 `docs/m2-real-llm-final-report.md`）|

## 时间线建议

- **本周**：业务方提供 Dify URL + API key
- **下周一**：完成 shadow_compare 端到端联调
- **下周二-周日**：跑 24h shadow + 收 diff 报告
- **再下周**：根因分析 + 修补 + 金丝雀准备

## 如有疑问

- 技术细节：联系 LangGraph 工程团队
- ADR 决策：见 `docs/adr/`（ADR 0000-0020 共 21 篇）
- M2 收尾报告：`docs/m2-real-llm-final-report.md`

谢谢配合。

---

**邮件正文结束。寄送前请加业务方对接人姓名 + 抬头。**
