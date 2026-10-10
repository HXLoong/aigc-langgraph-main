<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 app/prompts/CLAUDE.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->

# app/prompts · 局部陷阱

> 提示词纪律（PromptSpec、占位符、加载方式、来源优先级）只在 `.claude/rules/prompt-management.md` 维护。
> 本文件只补该目录的**易错点 + `.md` 文件格式**。

## 易错点

- **目录名是 `option_close/`，不是 `close/`**（历史命名）；子图代码侧是 `app/subgraphs/close/`，两边不对称
- **四个互斥 PromptSpec** 在 `app/parsing/prompts.py`：option / swap / option_close / router 的 `parse_instruction`；`system/capability_probe.md` 仅供本地验收预检，不参与业务解析。
- **`_versions.yaml` / `gray` / `resolve_prompt_version` 是待清理旧形态**：ADR 0003 现行版本化是 git 分支 + 单文件
- **字段描述**由 `app/parsing/*_fields.py` 与 `models.py` 的 `Field(description=...)` 定义。字段值和证据分别表达；提示词不复制字段表或 JSON 骨架。
- Dify YAML 快照只作历史证据（commit `fddd94e`，ADR 0024 D1），不再同步

## .md 文件格式（4-backtick 外层 fence 才不会被内层 ``` 提前闭合）

````markdown
# 提示词标题

## [system]
```
<system 提示词内容；由代码渲染的 {{var}} 须在 PromptSpec.injects 登记>
```

## [user]        ← 仅当 user 含规则文本时才有（当前四套解析器不使用）
```
<user 模板，{{var}} 经 render_user() 渲染>
```
````
