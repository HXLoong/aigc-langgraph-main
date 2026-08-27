# ADR 0002 · 建设综合运行时 Harness（开发期 + 运行期 + 提示词调优期三位一体）

- 状态：已采纳（2026-05-13 由 proposed 转正，M1+M2 落地印证）
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #139）
- 作者：图灵科技 + Tony

## 上下文

[ADR 0000](./0000-migrate-from-dify-to-langgraph.md) 列出了 Dify 留下的四个痛点（业务逻辑藏在提示词、无法监测、无法回归、无法评估）。我们决定把"评估 Harness"目标定义为 **综合运行时 Harness**，而不只是单一的"评测脚本"或"CI 测试金字塔"。

**目标定义**：让"提示词改一行"或"节点逻辑改一行"成为一个有 CI、有指标、有 review 流程的工程动作，而不是 Dify UI 上一次黑盒保存。

## 三个阶段的覆盖面（现状）

- **开发期**：节点 / 子图 / 模型层单元测试（`tests/` 977 项 collected）+ in-process 闭环 demo（`scripts/demo_closed_loop.py`，零外部依赖跑全量 golden）+ 子图金字塔。
- **运行期**：每个节点产出结构化 trace 写入 MySQL `node_trace` 表（`app/nodes/persist.py`），对接 **LangFuse**（[ADR 0014](./0014-langfuse-as-harness-backend.md)，取代早期 LangSmith 方案）+ OpenTelemetry（`app/observability/tracing.py`），基于 `/metrics` 做延迟、错误率告警（`app/observability/{metrics,alerts}.py`）。
- **提示词调优期**：提示词版本化（`app/prompts/_versions.yaml` + [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md)）+ golden set 自动评分（`scripts/eval_golden.py` / `scripts/langfuse_eval.py` DeepSeek Judge）+ A/B 流量染色（conversation_id 稳定 hash 分流，`swap.intent` 95/5 灰度在跑）。

## 备选方案

- **A. 评估 Harness（仅 lm-eval 风格的离线评分）**：解决"提示词调优期"，但开发期的回归测试、运行期的监测都无解。
- **B. 测试 Harness（仅 CI 回归框架）**：解决"开发期"，但提示词调优要素和线上监测缺失。
- **C. 综合运行时 Harness（已选）**：覆盖三个阶段，是四个痛点真正的对应解。代价是建设范围更大、分阶段落地。

## 阶段进度（2026-08-27）

| Phase | 内容 | 状态 |
|---|---|---|
| 1 | 闭环 demo + golden set + shadow_compare | ✅（golden 已从 30 条扩到 **535 条主集 + 34 条 ticker**，B/C/D 桶管理）|
| 2 | 节点级 trace 落库 + trace 后台接入 | ✅（`node_trace` + LangFuse CallbackHandler；后台由 LangSmith 换为 LangFuse，[ADR 0004](./0004-trace-granularity-node-level-with-langsmith.md) / 0014）|
| 3 | 提示词版本化 + 评分自动化 + A/B 染色 | ✅（三件套均落地，见上；[ADR 0003](./0003-prompt-versioning-by-file-coexistence.md)）|
| 4 | 线上 trace → 人工标注 → golden 反哺 | 🔄 平台已选定 LangFuse（trace/dataset/eval/annotation 四件套），`scripts/upload_golden_to_langfuse.py` / `harness sync-golden` 已就绪；标注运营与 D 桶回流待跑（[ADR 0005](./0005-annotation-roles-judge-plus-business-spotcheck.md)、二期 Issue #37）|

## Harness 工程落地

`harness/` 顶层目录（与 `app/` 解耦）：`runner` / `differ` / `golden` / `reporter` / `cli` / `langfuse_client` / `token_tracker` / `case_generator/`（LLM 对抗式 paraphrase 造 C 桶）+ `__main__.py`。

注意两点现状（详见核查 [#139](https://github.com/GZTL-AI/aigc-langgraph/issues/139)、[#142](https://github.com/GZTL-AI/aigc-langgraph/issues/142)）：

- CLI 的 `eval` / `diff` / `sync-golden` 子命令仍是 stub（退出码 64）；**评估主入口是 `scripts/langfuse_eval.py`**（M3 主用）。
- harness 运行成本已可度量：`harness/token_tracker.py` + `scripts/llm_cost_report.py`。

## 后果

- 不把 shadow_compare 当作迁移成功的唯一指标——它只是 Phase 1 的产出（且已被 [ADR 0016](./0016-m3-scope-engineering-loop-not-shadow.md) 定位为 M4 第二意见），不能替代 Phase 3/4 的提示词评估能力。
- 每加一个意图/子图，必须同步生产 golden case + trace schema 字段——已由 CI 的 `scripts/check_fixture_consistency.py` 与 `.claude/skills/add-intent` 技能工程化。
- `app/prompts/` 不允许退化成无版本号的扁平目录——`_versions.yaml` 是 A/B 真源，见 ADR 0003；当前的治理债（>2 并存版本）见裁决 issue [#159](https://github.com/GZTL-AI/aigc-langgraph/issues/159)。
