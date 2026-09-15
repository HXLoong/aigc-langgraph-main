# ADR 0022 · 代码迁移完成后的提示词治理模型

- 状态：**部分采纳**（D2 / D3 / D6 已落地；D1 真源切换 与 D4 瘦身放量 需业务方 + 用户拍板）
- 日期：2026-09-15
- 起源：客户反馈 Dify 迁移过来的提示词"太臃肿、冗余多"；专题评估见 [docs/prompt-maintainability-assessment.md](../prompt-maintainability-assessment.md)
- 修订：[ADR 0003](./0003-prompt-versioning-by-file-coexistence.md)（删除第二种版本化形态）、[ADR 0001 D5](./0001-rewrite-app-with-harness-first.md)（处置表登记制改为 manifest + lint）
- 作者：图灵科技 + Tony

## 上下文

代码迁移（DSL v2，2026-08-28）完成后，`app/prompts/` 有 41 个业务 `.md`、system 段合计约 48 万字符（≈ 30 万 tokens），其中生产活跃 28 个 / 灰度 5 个 / 非活跃 8 个。提示词的**内容**问题（错例回填规则、重复陈述、structured output 下失效的 JSON 格式禁令、悬空变量、硬编码业务数据）在 swap 域已由 `docs/swap-prompt-slimming-assessment.md` 定性，本次评估扩到 option / option_close / ticker / router 全域。

比内容更根本的是**管理**问题——同样的内容病灶会在下一次 Dify 同步后重新长回来：

1. **真源之争**：ADR 0014 D3-2 规定生产真源是 git `.md`；2026-09-11 又按用户要求把 7 个文件回归为 `dify/yaml/场外交易-test.yml` 原文并用 `tests/test_prompt_governance.py` 逐字锁定。任何对这 7 个文件的瘦身都会让测试失败。更重要的是**锁定守的是文本相等而非代码契约**：这次回归把 Dify 靠 code 节点前置分流的 `confirm_order` 从提示词枚举中删掉，代码 Literal / 路由 / 二次校验没有同步，互换确认下单链路一度不可达（评估 SW-INC-01，已补前置分流）。
2. **活跃/非活跃靠手写**：`app/prompts/CLAUDE.md` 手写"禁止直接删"清单，其中 `swap/place_order.dify_original.md`、`swap/v2/` 已不存在；没有机器可读清单，也没有"每个 .md 必须有加载点"的守护。
3. **三套版本化形态并存**：`_versions.yaml` 同目录灰度（在用）、`compose_prompt` + `swap/v2/` 子目录拼装（零调用点、目录不存在）、`promote_langfuse_prompt` 的 `_v{N+1}` 晋升；ADR 0003 ">2 并存版本视为治理债"无执行机制。
4. **v2 灰度位漂移无防护**：2026-08-28 切出的 `swap/intent_v2` / `place_order_v2` 在 09-11 v1 被 Dify 更新后没有同步，若此时放量会丢规则。
5. **`.md` 契约有死区**：所有节点只用 `prompt.system`，`[user]` 段与 `render_user()` 在 `app/` 内零调用点，却仍被同步与逐字断言；`node_id` / `model` 元数据无代码消费。

## 决策

### D1 · 真源：git `.md` 是唯一生产真源，Dify 降为上游输入（**待拍板**）

两种模型的对比：

| | A · Dify 为真源，git 只读镜像（现状 09-11 后） | B · git 为真源，Dify 为上游输入（推荐） |
|---|---|---|
| 瘦身落地方式 | 只能走 `*_v2.md` 灰度位；v1 永远等于 Dify 原文 | 直接改 v1（经 eval 门），Dify 更新走 `export_dify_prompts.py --overwrite` 前人工 diff 选择性合入 |
| Dify 侧更新 | 全量覆盖 v1，本地修复丢失（09-11 已发生一次） | 以 diff 形式呈现，人工决定合入哪些 |
| 与 ADR 0014 D3-2 | 冲突（D3-2 说真源是 git） | 一致 |
| `test_prompt_governance.py` | 逐字锁定 7 文件 | 改为 **Dify 快照漂移告警**：登记 7 个 node_id 的 prompt sha，Dify YAML 变化时提示"上游有更新待合入"，不阻断本地修改 |
| 客户诉求"瘦身" | 只能在灰度位实现，且 v2 会持续漂移 | 可以真正落地 |

推荐 B。前提：业务方确认 Dify 工作流不再是生产路径（M4 全量切换后自然成立），在此之前维持 A，瘦身全部走 `*_v2.md`。切换动作只有一处：把 `test_prompt_governance.py` 的相等断言改为快照漂移告警。

### D2 · `app/prompts/_manifest.yaml` 是活跃/灰度/非活跃的机器可读真源（已落地）

- 每个 `.md` 必须登记 `status: active | gray | inactive`；`scripts/prompt_inventory.py --check` 进 CI 守四条不变量：
  1. 目录 ↔ manifest 双向无孤儿
  2. `active` 的 `loader` 文件存在且引用了字面量 name
  3. `inactive` 在 `app/` 内零 `load_prompt` 引用，且 `reason` 必填（保留理由 + 可删条件）
  4. `gray` 记录 `base_system_sha256`（切 v2 时 v1 的 system 快照），v1 之后被改 → 报"漂移"，必须重做 diff 并写 `drift_acknowledged`
- `python scripts/prompt_inventory.py` 同时产出字符数 / 估算 tokens / JSON 禁令行数 / Dify 占位符数 / `[user]` 段字符数，替代人工 `wc -m`
- `app/prompts/CLAUDE.md` 不再手写非活跃清单，只指向 manifest
- 取代 ADR 0001 D5 "处置表登记制"中的**资产状态**部分；D5 表继续登记**改写决定**（合并 / 拆分 / 瘦身批次）

### D3 · 版本化形态收敛为一种：同目录并存 + `_versions.yaml`（已落地）

- 删除 `compose_prompt()` 与 `Settings.swap_prompt_version`（#159 遗留裁决），`tests/test_prompt_inventory.py` 防复活
- `promote_langfuse_prompt.py` 产出的 `_v{N+1}.md` 同样按 D2 登记为 `gray`
- ">2 并存版本视为治理债"由 manifest 的 `gray` 条目数可见化；转正时 v2→v1 并注销条目

### D4 · 瘦身纪律：三档 + 错例转 golden + 死重一律删（**放量待业务方**）

沿用 swap 评估报告的三档：

| 档 | 内容 | 门槛 |
|---|---|---|
| 零风险 | structured output 下的 JSON 格式禁令；未注入变量的悬空规则；同一规则 2~9 遍收敛为 1 处；自相矛盾的修订史；示例污染防护三大段 | eval PASS ≥ v1 基线 |
| 低风险 | few-shot 去重；自检清单与正文去重；闭集词表改"语义类 + 少量锚例" | eval + 抽样人工比对 |
| 需业务确认 | 硬编码产品名 / 名称词典 / 真实账户与员工名（P0 红线）；低频输入形态整段降级；提示词承诺但代码未实现的后处理 | 业务方逐条确认 |

原则：**错例回填规则转 `tests/fixtures/` golden，提示词只留通用原则**；LLM 干确定性活（订单号提取、量词展开、时间补零、表格模式判定）下沉代码，参照 `app/subgraphs/swap/order_id.py` 先例。

### D5 · `.md` 契约瘦身（已落地一半）

- `[user]` 段：保留作 Dify 原始输入形态参照，不再是运行时契约；节点 user 消息由代码拼装
- `{{#node.var#}}` 占位符：只允许出现在**代码确实注入了对应值**的位置（由代码-提示词契约评估逐文件核对）；未注入的占位符视为悬空规则，属零风险删除档
- `node_id` / `model` 元数据：仅供 Dify 对照，无代码消费

### D6 · 非活跃资产处置（已落地）

8 个 `inactive` 条目的保留理由与可删条件写在 manifest `reason` 字段。M4 全量上线稳定 7 天后按 reason 逐条清理；Dify 原始快照类归档到 `docs/archive/dify-originals/`（已有先例）而非留在 `app/prompts/`。

## 备选方案

- **提示词进数据库 / 后台管理**：回到迁移前"提示词不在代码里"的问题（ADR 0003 已否决）
- **LangFuse 为生产真源**：ADR 0014 D3-2 已否决（绕过 git PR 审计）
- **保持 CLAUDE.md 手写清单**：已被证明会陈旧（本次核查发现 2 处引用不存在的文件）

## 后果

- 正面：新增 / 删除 / 去 LLM 化提示词有机器守护；v2 漂移在 CI 可见；瘦身有明确档位与门槛；版本化只剩一种心智模型
- 负面：每加一个 `.md` 多登记一次；D1 切换前 7 个锁定文件的瘦身只能走 v2，且 v2 需随 Dify 更新重做 diff
- 未决：D1 的切换时点；D4 需业务确认档的逐条裁决；ticker 4 个提示词转 structured output（消除原文 JSON 解析与 `<result>` 标签指令）

## 关联

- [ADR 0001 D5](./0001-rewrite-app-with-harness-first.md) · 改写登记 → 本 ADR D2 接管资产状态
- [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md) · 同目录并存 → 本 ADR D3 收敛为唯一形态
- [ADR 0014](./0014-langfuse-as-harness-backend.md) · D3-2 git 真源 → 本 ADR D1 沿用
- `docs/swap-prompt-slimming-assessment.md` · swap 域内容评估 → 本 ADR D4 三档口径来源
- `docs/prompt-maintainability-assessment.md` · 本次全域评估
