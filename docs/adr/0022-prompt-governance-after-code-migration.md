# ADR 0022 · 代码迁移完成后的提示词治理模型（历史存根）

- 状态：**已废弃**（2026-09-16，机制已从代码库移除；契约治理由 [ADR 0023](./0023-prompt-as-code-langgraph.md) 承担）
- 日期：2026-09-15
- 作者：图灵科技 + Tony

## 原决策

客户反馈迁移来的提示词"臃肿、冗余多"，本 ADR 提出：

1. **git `.md` 是唯一生产真源，Dify 降为上游输入**——此条保留，并由 [ADR 0024](./0024-langgraph-native-rearchitecture.md) D1 进一步推进为"Dify 退出上游"；
2. 用 manifest 清单 + lint 机器守护提示词的 活跃 / 灰度 / 非活跃 状态；
3. 版本化形态收敛为"同目录并存 + `_versions.yaml`"一种（见 [ADR 0003](./0003-prompt-versioning-by-file-coexistence.md)）；
4. 瘦身分三档：零风险（直接删）/ 低风险（eval + 抽检）/ 需业务确认（逐条确认）；错例规则转为数据集用例，提示词只留通用原则。

## 为何废弃

Dify 退出上游后，上游漂移告警与 manifest 登记失去对象；ADR 0023 的 PromptSpec 注册表以代码对象直接表达"哪个节点加载哪个提示词"，manifest 成为重复维护。2026-09-16 整套 manifest + lint 移除，改提示词走普通 PR review。原文见 [实施记录归档](../archive/history/adr-implementation-log-2026-09.md)。

## 仍有效的经验

- 瘦身三档与"错例转数据集、确定性工作下沉代码"两条原则仍适用于提示词维护。
- 专题评估：[docs/prompt-maintainability-assessment.md](../prompt-maintainability-assessment.md)。
