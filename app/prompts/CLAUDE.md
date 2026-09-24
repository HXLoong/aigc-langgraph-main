# app/prompts · 局部陷阱

> 提示词纪律（PromptSpec、占位符、加载方式、来源优先级）只在 `.claude/rules/prompt-management.md` 维护。
> 本文件只补该目录的**易错点 + `.md` 文件格式**。

## 易错点

- **目录名是 `option_close/`，不是 `close/`**（历史命名）；子图代码侧是 `app/subgraphs/close/`，两边不对称
- **`judge/` 与 `system/` 不是 PromptSpec**：`judge/option_judge.md` 由 `scripts/langfuse/langfuse_eval.py`、
  `system/capability_probe.md` 由 `scripts/local_eval.py` 直接 `load_prompt`；14 个 PromptSpec 只覆盖业务节点
- **`_versions.yaml`** 是 ADR 0003 灰度的真源，loader 只读其中 `overrides:` 段；不要在 Python 里写死版本。
  当前无灰度位，需要时新建 `<name>_v{N}.md` 并登记
- **候选抽取的字段描述**用字段上的 `CandidateDescription` 元数据（`app/extraction/fields.py`），与最终 DTO 语义分离，
  不要写进 `.md`
- Dify YAML 快照只作历史证据（commit `fddd94e`，ADR 0024 D1），不再同步

## .md 文件格式（4-backtick 外层 fence 才不会被内层 ``` 提前闭合）

````markdown
# 提示词标题

## [system]
```
<system 提示词内容；由代码渲染的 {{var}} 须在 PromptSpec.injects 登记>
```

## [user]        ← 仅当 user 含规则文本时才有（现仅 swap/fresh_counterparty.md）
```
<user 模板，{{var}} 经 render_user() 渲染>
```
````
