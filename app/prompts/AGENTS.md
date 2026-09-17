<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 app/prompts/CLAUDE.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->

# app/prompts · 局部约定

> 提示词管理规则见 `.claude/rules/prompt-management.md`（来源优先级 / 改写纪律 / 占位符）。
> 子目录布局见根 `CLAUDE.md` 的「项目结构」段。本文件只补**易错点 + 文件格式 + 字符数提示**。

## 易错点

- **目录名是 `option_close/`，不是 `close/`**（历史命名）；子图代码侧是 `app/subgraphs/close/`，两边不对称
- **`_versions.yaml`** 才是 ADR 0003 A/B 灰度的真源；不要在 Python 里写死版本。当前无灰度位，需要时新建 `<name>_v{N}.md` 并登记
- **git `.md` 是唯一生产真源**（ADR 0024 D1）：Dify 已退出上游地位，没有同步 / 导出链路；YAML 快照冻结在 tag `dify-assets-frozen-20260917（指向 commit fddd94e；tag 仅存本地，远端拒绝 tag 推送，维护者可从该 sha 重建）`
- **一个 LLM 节点 = 一个 `PromptSpec`**（`app/prompts/spec.py`，ADR 0023）：`inputs` 必须是 AgentState 字段（构造期校验）、
  `output_model` 每个字段写 `Field(description=)`（输出语义唯一真源，`.md` 不再放 JSON 骨架）、`injects` 登记 `.md` 里由代码渲染的占位符、
  `user_builder` 只拼变量。共享积木在 `blocks.py`，不要在子图复制 `_format_history`
- `[user]` 段**只有**当 user 含规则文本时才存在（`swap/place_order.md`、`swap/fresh_counterparty.md`），用 `{{var}}` 占位并经
  `render_user()` 渲染，是运行时契约；其它节点没有 `[user]` 段，user 消息由 `user_builder` 拼变量

## .md 文件格式约定（4-backtick 外层 fence 才不会被内层 ``` 提前闭合）

````markdown
# 提示词标题

## [system]
```
<system 提示词内容；由代码渲染的 {{var}} 须在 PromptSpec.injects 登记>
```

## [user]        ← 仅当 user 含规则文本时才有
```
<user 模板，{{var}} 经 render_user() 渲染>
```
````

占位符：现役 system 占位符只有 `{{counterparty_list}}`（`close/holding_query.py`、`swap/multimodal.py`）与 `{{current_date}}`
（`ticker/tools.py`），均在 `PromptSpec.injects` 登记；代码不注入的占位符就是悬空规则，属零风险删除档——不要指望 LLM 把变量名当上下文。

## 字符数提示（影响延迟）

- 单请求提示词开销按调用链上各 `.md` system 字符 ÷1.6 估算 tokens；
  当前最重路径：互换图片下单 ≈ 54K tokens、平仓下单 ≈ 37K、互换文本下单 ≈ 36K（详见 `docs/prompt-maintainability-assessment.md`）
- 长提示词显著影响 P95 延迟，评估时关注延迟指标
