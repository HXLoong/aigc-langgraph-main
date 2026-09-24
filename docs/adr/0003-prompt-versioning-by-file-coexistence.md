# ADR 0003 · 提示词版本化采用"同目录文件并存"

- 状态：已采纳（机制在位，当前无在跑灰度）
- 日期：2026-05-10
- 作者：图灵科技 + Tony

## 决策

提示词新版本与当前版本在同一目录并存：`swap/intent.md` 为生产版本，新版命名 `swap/intent_v2.md`。灰度期间两版同时存活，按代码逻辑切流，无需双部署或双镜像。这是本项目**唯一**的版本化形态。

选版链路：

```
app/prompts/_versions.yaml（灰度配置，如 95% intent / 5% intent_v2）
  → resolve_prompt_version(category, name, conversation_id)
      · 按 conversation_id 稳定 hash 分流（同一会话恒命中同一版本）
      · 环境变量 OTC_PROMPT_<CAT>_<NAME>_VERSION 可强制覆盖（调试用）
  → load_prompt(category, name)
```

## 纪律

- **灰度前置条件**：节点必须先把 `PromptSpec.build_messages` 返回的 `prompt_name` 写入 trace，才能进 `_versions.yaml`，否则版本对比失真。
- **清理规则**：新版满一个灰度周期且稳定 7 天后，转正（去后缀）并删除旧版；同一提示词并存版本不超过 2 个。

## 备选方案

- **同目录并存（已选）**：单部署即可灰度，回滚成本低。
- **git 分支 + 单文件**：需双分支双部署，过度复杂。
- **数据库存储 + 后台管理**：回到迁移前"提示词不在代码里"的问题。

## 现状

现状：`_versions.yaml` 无灰度条目。
