# ADR 0003 · 提示词版本化：git 分支 + 单文件

- 状态：已采纳（形态为 git 分支 + 单文件；旧代码待迁移）
- 日期：2026-05-10
- 关系：2026-09-29 由"同目录文件并存"改为"git 分支 + 单文件"；提示词真源与 PromptSpec 见 [ADR 0023](./0023-prompt-as-code-langgraph.md)；灰度切流沿用按群 `agentUrl` 的金丝雀模型（[ADR 0024](./0024-langgraph-native-rearchitecture.md)）
- 作者：图灵科技 + Tony

## 背景

生产切流是**部署级**的：客户侧 Java 配置管理员按群把 `agentUrl` 指向哪个部署，`app/observability/canary.py` 明确 LangGraph 服务侧不做流量分配。灰度因此天然是"哪几个群打到哪个版本"，同一会话的版本一致性由"同一群始终打到同一部署"保证，不需要在进程内再按 `conversation_id` 分流。

进程内分流的代价反而长期存在：同一提示词要维护两份并存文件、loader 多一层版本选择、`PromptSpec` 多一个 `gray` 开关，还要靠人记并存版本清理规则。截至 2026-09-29，真源 `app/prompts/_versions.yaml` 中没有任何灰度条目（[ADR 0002](./0002-comprehensive-runtime-harness.md) 调优期）。

## 决策

提示词一个名字一个文件：`swap/intent.md` 始终是现行版本，目录内不出现 `_v2` 之类的并存版本。**这是本项目唯一的版本化形态。**

- **版本 = git 分支 / commit**：新版提示词在主题分支上改、走 PR review，合入 `main` 即转正；未合入的版本只存在于分支，不落地成并存文件。
- **灰度 = 双部署 + 按群切流**：出金丝雀镜像、部署第二实例，把测试群的 `agentUrl` 指向金丝雀部署，其余群保持稳定部署。回滚 = `agentUrl` 切回稳定部署，或回滚镜像（值班手册 §7）。
- **调试覆盖只在非生产**：环境变量 `OTC_PROMPT_<CATEGORY>_<NAME>_VERSION` 继续用于 staging / 本地演练指定替代提示词文件；该文件不进生产部署，不作为生产灰度手段。

## 纪律

- 节点仍把 `PromptSpec.build_messages` 返回的 `prompt_name` 写进 `TraceEntry.llm_output["prompt_name"]`，用于定位与回放；它不再承担灰度前置条件。
- 分支合并后删除分支；不保留并存提示词文件；镜像保留上一版供回滚。

## 备选方案

- **git 分支 + 单文件（已选）**：与按群 `agentUrl` 切流一致，提示词改动就是普通 PR；无并存文件、无 hash 分流、无额外选择层。
- **同目录文件并存 + `_versions.yaml`（原形态）**：能在单部署内做会话级分流，但需要并存文件、hash 分流、trace 硬前置与并存版本清理，且没有实际灰度场景；代码待清理（见[工作计划](../work-plan.md)）。
- **数据库存储 + 后台管理**：回到迁移前"提示词不在代码里"的问题（[ADR 0000](./0000-migrate-from-dify-to-langgraph.md)）。

## 现状

代码仍实现同目录并存：`app/prompts/__init__.py` 的 `resolve_prompt_version` / `_load_versions_config`、`app/prompts/spec.py` 的 `gray` 开关、`app/prompts/_versions.yaml`，以及 5 处 `gray=True` 的 PromptSpec（互换意图、互换下单、多模态三处）；清理与测试调整见[工作计划](../work-plan.md)。提示词真源不变：git 里的 `app/prompts/**/*.md`（[ADR 0014](./0014-langfuse-as-harness-backend.md) D3）。
