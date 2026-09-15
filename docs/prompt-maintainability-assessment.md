# 提示词可维护性专题评估（全域）

> 编写：图灵科技 · 2026-09-15 · 分支 `claude/gallant-hopper-c7ju7v`
> 背景：客户反馈从 Dify 迁移过来的提示词"太臃肿、冗余多"。2026-08-28 的 `docs/swap-prompt-slimming-assessment.md` 只覆盖 swap 域；本报告把评估扩到 option / option_close / ticker / router 全域，并把重点从"内容"移到"代码迁移完成后提示词怎么管才易于维护"。
> 方法：动态工作流 7 路并行评估（5 个提示词域 + 治理层 + 代码-提示词契约）→ 每路独立对抗核证（只采信 confirmed / partial 的发现）→ 完整性批评。字符数口径：Python `len()`（Unicode 字符）；token 为估算（字符 ÷ 1.6，与 swap 报告同口径）。
> 决策落点：[ADR 0022](./adr/0022-prompt-governance-after-code-migration.md)。

---

## 一、执行摘要

（评估工作流进行中，本节随核证结果补齐。）

## 二、全域盘点（`python scripts/prompt_inventory.py` 生成）

| 提示词 | 状态 | 加载点 | system 字符 | ≈tokens | JSON 禁令行 | Dify 占位符 | user 段字符 |
|---|---|---|---:|---:|---:|---:|---:|
| `judge/option_judge` | active | `scripts/langfuse_eval.py` | 427 | 267 | 1 | 0 | 0 |
| `option/extract_cancel` | active | `app/subgraphs/option/extract_cancel.py` | 1,344 | 840 | 0 | 0 | 44 |
| `option/extract_cancel_place` | active | `app/subgraphs/option/extract_cancel_place.py` | 1,116 | 698 | 0 | 0 | 44 |
| `option/extract_confirm_cancel` | active | `app/subgraphs/option/extract_confirm_cancel.py` | 1,325 | 828 | 0 | 0 | 44 |
| `option/extract_confirm_place` | active | `app/subgraphs/option/extract_confirm_place.py` | 3,171 | 1,982 | 0 | 0 | 73 |
| `option/extract_inquiry` | active | `app/subgraphs/option/extract_inquiry.py` | 11,281 | 7,051 | 0 | 0 | 0 |
| `option/extract_place` | active | `app/subgraphs/option/extract_place.py` | 4,056 | 2,535 | 0 | 1 | 0 |
| `option/extract_query` | active | `app/subgraphs/option/extract_query.py` | 1,320 | 825 | 0 | 0 | 44 |
| `option/intent` | active | `app/subgraphs/option/intent.py` | 7,257 | 4,536 | 0 | 5 | 162 |
| `option/intent_extract` | inactive | `-` | 65,711 | 41,069 | 0 | 0 | 0 |
| `option/param_limit` | inactive | `-` | 8,171 | 5,107 | 0 | 1 | 31 |
| `option_close/cancel_close` | active | `app/subgraphs/close/cancel_close.py` | 4,497 | 2,811 | 1 | 2 | 79 |
| `option_close/confirm_cancel` | active | `app/subgraphs/close/confirm_cancel.py` | 7,815 | 4,884 | 1 | 2 | 79 |
| `option_close/confirm_close` | active | `app/subgraphs/close/confirm_close.py` | 3,224 | 2,015 | 1 | 2 | 79 |
| `option_close/holding_query` | active | `app/subgraphs/close/holding_query.py` | 6,471 | 4,044 | 1 | 2 | 36 |
| `option_close/intent` | active | `app/subgraphs/close/intent.py` | 7,135 | 4,459 | 0 | 3 | 31 |
| `option_close/place_close` | active | `app/subgraphs/close/place_close.py` | 52,702 | 32,939 | 0 | 12 | 687 |
| `option_close/query_status` | active | `app/subgraphs/close/query_status.py` | 492 | 308 | 0 | 1 | 38 |
| `router/unknown_intent` | active | `app/nodes/intent_route.py` | 8,836 | 5,522 | 0 | 2 | 90 |
| `swap/cancel_order` | inactive | `-` | 1,360 | 850 | 2 | 2 | 91 |
| `swap/confirm` | inactive | `-` | 1,063 | 664 | 2 | 0 | 104 |
| `swap/confirm_cancel` | inactive | `-` | 1,063 | 664 | 2 | 2 | 91 |
| `swap/confirm_modify` | inactive | `-` | 1,188 | 742 | 2 | 2 | 91 |
| `swap/confirm_order` | inactive | `-` | 1,572 | 982 | 2 | 2 | 91 |
| `swap/excel_extract` | active | `app/subgraphs/swap/multimodal.py` | 14,775 | 9,234 | 5 | 0 | 0 |
| `swap/excel_extract_v2` | gray | `swap/excel_extract` | 9,111 | 5,694 | 0 | 0 | 0 |
| `swap/image_extract` | active | `app/subgraphs/swap/multimodal.py` | 67,246 | 42,029 | 18 | 0 | 0 |
| `swap/image_extract_v2` | gray | `swap/image_extract` | 55,266 | 34,541 | 0 | 0 | 0 |
| `swap/image_ocr` | active | `app/subgraphs/swap/multimodal.py` | 7,312 | 4,570 | 0 | 1 | 0 |
| `swap/image_ocr_v2` | gray | `swap/image_ocr` | 6,404 | 4,002 | 0 | 0 | 0 |
| `swap/intent` | active | `app/subgraphs/swap/intent.py` | 12,314 | 7,696 | 1 | 4 | 250 |
| `swap/intent_v2` | gray | `swap/intent` | 4,516 | 2,822 | 0 | 3 | 250 |
| `swap/place_order` | active | `app/subgraphs/swap/place_order.py` | 39,046 | 24,404 | 2 | 3 | 216 |
| `swap/place_order_v2` | gray | `swap/place_order` | 33,309 | 20,818 | 0 | 3 | 799 |
| `swap/query_order` | inactive | `-` | 1,337 | 836 | 2 | 2 | 91 |
| `swap/select_counterparty` | active | `app/subgraphs/swap/select_counterparty.py` | 2,817 | 1,761 | 0 | 3 | 137 |
| `swap/select_ticker` | active | `app/subgraphs/swap/select_ticker.py` | 2,906 | 1,816 | 0 | 3 | 143 |
| `ticker/infer_code` | active | `app/subgraphs/ticker/tools.py` | 7,291 | 4,557 | 1 | 4 | 26 |
| `ticker/judge_type` | active | `app/subgraphs/ticker/tools.py` | 609 | 381 | 1 | 1 | 26 |
| `ticker/rank` | active | `app/subgraphs/ticker/tools.py` | 6,198 | 3,874 | 1 | 5 | 160 |
| `ticker/tokenize` | active | `app/subgraphs/ticker/tools.py` | 10,562 | 6,601 | 2 | 1 | 31 |

| 状态 | 文件数 | system 字符合计 | ≈tokens |
|---|---:|---:|---:|
| active | 28 | 293,545 | 183,466 |
| gray（v2 灰度位，0 流量） | 5 | 108,606 | 67,879 |
| inactive | 8 | 81,465 | 50,916 |

**单请求提示词开销（按调用链累加 system 段）**：

| 请求路径 | system 字符 | ≈tokens |
|---|---:|---:|
| 互换图片下单（intent + image_ocr + image_extract） | 86,872 | 54,295 |
| 平仓下单（intent + place_close） | 59,837 | 37,398 |
| 互换文本下单（intent + place_order + select_counterparty + select_ticker） | 57,083 | 35,677 |
| 互换 Excel 下单（intent + excel_extract） | 27,089 | 16,931 |
| 标的识别（infer_code + tokenize + judge_type + rank，并行） | 24,660 | 15,412 |
| 期权询价（intent + extract_inquiry） | 18,538 | 11,586 |
| 平仓确认撤单（intent + confirm_cancel） | 14,950 | 9,344 |
| 期权下单（intent + extract_place） | 11,313 | 7,071 |
| unknown 兜底 | 8,836 | 5,522 |

三个 3 万 tokens 以上的路径（图片下单 / 平仓下单 / 文本下单）是延迟与成本的主要单点；option 域相对健康。

## 三、管理层现状（评估前已核实的事实）

| # | 事实 | 证据 |
|---|---|---|
| 1 | 所有节点只用 `prompt.system`；`.md` 的 `[user]` 段与 `Prompt.render_user()` 在 `app/` 内零调用点（合计 4,158 字符仍被同步与逐字断言） | `grep -rn "prompt.system\|render_user" app/` |
| 2 | 2026-09-11 e72ee2d 把 7 个文件回归为 `dify/yaml/场外交易-test.yml` 原文，并用 `tests/test_prompt_governance.py` 逐字锁定 | `git show --stat e72ee2d` |
| 3 | 与此同时 `swap/intent_v2` / `place_order_v2`（08-28 切出）未同步 v1 的更新 → 灰度位已漂移 | v1 system sha 在 1664739 / adcc436 与 HEAD 不同 |
| 4 | `compose_prompt` + `swap/v2/` 子目录形态零调用点、目录不存在；`Settings.swap_prompt_version` 死配置 | ADR 0003 #159 待裁决项 |
| 5 | `app/prompts/CLAUDE.md` 手写清单引用了不存在的 `swap/place_order.dify_original.md`、`swap/v2/` | 目录 `find` |
| 6 | Dify 有两份 YAML（`主干工作流.yml` / `场外交易-test.yml`），`select_counterparty` / `select_ticker` 两处内容不同；`场外交易-test.yml` 新增 LLM 节点「互换-全新下单交易对手识别」在 `app/prompts` 无对应文件 | 解析 YAML `llm` 节点 |
| 7 | 评估守护断裂：2026-09-10 f37ac0d 把 golden 移到 `tests/fixtures/old_typing/`，`scripts/check_fixture_consistency.py` 恒 exit 2、`check_adr_refs.py` 报 3 处路径不存在；CI 自 05-12 起仅 `workflow_dispatch` 触发，无人发现。瘦身的"eval PASS ≥ v1 基线"门槛当前没有可自动运行的载体（`plan0909.md` 正在重建） | 本地运行两脚本 |
| 8 | ticker 4 个提示词走 `_call_ticker_llm` 原文 JSON 解析（`<result>` 标签），非 `with_structured_output` | `app/subgraphs/ticker/tools.py:491-600` |

## 四、按域评估（核证后）

（工作流进行中。）

## 五、跨域病灶汇总

（工作流进行中。）

## 六、治理层评估与目标模型

（工作流进行中；结论已先行写入 ADR 0022 D1–D6。）

## 七、实施路线

（工作流进行中。）

## 八、本次已落地的改进

| 改动 | 说明 |
|---|---|
| `app/prompts/_manifest.yaml` | 41 个 `.md` 的 active / gray / inactive 登记，含 inactive 保留理由与 gray 的 v1 快照 sha |
| `scripts/prompt_inventory.py` + `tests/test_prompt_inventory.py` | 清单生成 + 四条不变量 lint，`--check` 已接入 `.github/workflows/ci.yml` |
| 删除 `compose_prompt()` / `Settings.swap_prompt_version` | #159 遗留死路径（ADR 0003 修订、handbook 8.7 改写） |
| `app/prompts/CLAUDE.md` 改写 | 手写非活跃清单 → 指向 manifest；修正 2 处不存在文件的引用 |
| ADR 0022 + ADR 0001 D5 登记 + ADR README 索引 | 治理模型决策 |
