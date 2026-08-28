# ADR 0003 · 提示词版本化采用"同目录文件并存"

- 状态：已采纳
- 日期：2026-05-10
- 修订：2026-08-27 深度改写为现状口径（wayfinder map #138 / 核查 #140）
- 作者：图灵科技 + Tony

## 决策

[ADR 0002](./0002-comprehensive-runtime-harness.md) Phase 3 需要提示词 A/B 与版本化能力。在文件层面采用**同目录并存**：`swap/intent.md` 是当前生产版本，新版叫 `swap/intent_v2.md`。A/B 期间两版同时存活，金丝雀流量按代码逻辑切分，不依赖双部署/双镜像。

## 落地现状（2026-08-27）

实际选版链路比原设计更完善，**以 `app/prompts/_versions.yaml` 为 A/B 真源**：

```
_versions.yaml（灰度配置，如 swap.intent = 95% intent / 5% intent_v2）
  → resolve_prompt_version(category, base_name, conversation_id)
      · conversation_id sha256 稳定 hash 分流（同会话恒命中同版本）
      · 环境变量 OTC_PROMPT_<CAT>_<NAME>_VERSION 可强制覆盖
  → load_prompt(category, name)   # 加载器不硬编码后缀，支持任意文件名
```

节点侧示例：`app/subgraphs/swap/intent.py` 先 `resolve_prompt_version` 再 `load_prompt`。原文"代码写死 `load_prompt("swap", "intent_v2")`"仅是临时调试用法。

**第二种版本化形态（原文未记录，本次补录）**：`compose_prompt(category, name, version)` + `swap/v2/` 子目录拼装（`_base.md` + 意图片段，字符数 -20%），由 `SWAP_PROMPT_VERSION` 配置选择。⚠️ 当前 `compose_prompt` 在 `app/` 内零调用点、`swap_prompt_version` 为死配置——接线或删除待裁决（[#159](https://github.com/GZTL-AI/aigc-langgraph/issues/159)）。

## 备选方案

- **同目录并存（已选）**：与 Dify 批量同步流程天然对齐，单部署即可灰度，回滚成本低。
- **git 分支 + 单一文件**：要双分支双部署，对 LLM 应用过度复杂。
- **数据库存储 + 后台管理**：回到迁移前"提示词不在代码里"的问题。

## 后果与纪律（现状口径）

- 加载器支持任意文件名 ✅；trace / 评估报告须记录实际加载的文件名——`harness/reporter.py` 已按 `prompt_name` 分桶统计。**A/B 前置纪律（#156 裁决）**：现仅 swap_intent 写 `prompt_name`（1/21），不批量回改；但**对任何提示词开启 A/B（进 `_versions.yaml`）前，其节点必须先在 trace 写入 `prompt_name`**，否则版本对比失真——此为 `_versions.yaml` 加条目的硬前置。
- **文件分两类，清理规则不同**（本次改写澄清原文与 `app/prompts/CLAUDE.md` "禁止直接删"的冲突）：
  - **A/B 实验位**（`*_v2.md` 等）：新版满一个金丝雀周期 + 稳定 7 天后清理、去后缀；
  - **Dify 原始快照 / 回滚资产**（`*.dify_original.md`、冻结的 `intent_extract.md` 等）：按 ADR 0001 D5 纪律保留，M4 前禁止删除。
- ">2 个并存版本视为治理债"目前**无执行机制且已被突破**（`swap/place_order` 3 变体；`ticker/tokenize*.md` 双死文件）——裁决见 [#159](https://github.com/GZTL-AI/aigc-langgraph/issues/159)。
- Dify 同步策略：原决策要求"拉下来的新版放 `_v{N+1}.md`、不覆盖原文件"。#159 已补保护：`scripts/export_dify_prompts.py` 默认跳过已存在文件，只有显式 `--overwrite` 才允许覆盖；覆盖前仍须人工 diff。
