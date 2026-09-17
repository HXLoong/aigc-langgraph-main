<!-- 自动生成：python scripts/sync_agents_md.py —— 禁止手改。
     真源是 app/prompts/CLAUDE.md；改那里再重新生成，提交前跑 python scripts/sync_agents_md.py --check 校验同步。 -->

# app/prompts · 局部约定

> 提示词管理规则见 `.claude/rules/prompt-management.md`（来源优先级 / 改写纪律 / Dify 同步 / 占位符）。
> 子目录布局见根 `CLAUDE.md` 的「项目结构」段。本文件只补**易错点 + 文件格式 + 字符数提示**。

## 易错点

- **目录名是 `option_close/`，不是 `close/`**（沿用 Dify 命名）；子图代码侧是 `app/subgraphs/close/`，两边不对称
- **`_versions.yaml`** 才是 ADR 0003 A/B 灰度的真源；不要在 Python 里写死版本
- **git `.md` 是唯一生产真源，Dify YAML 只是上游输入**：Dify 侧更新走 `sync.py` → `export_dify_prompts.py` → 人工 diff 合入，不要一键覆盖。
- 3 个 `swap/*_v2.md` 灰度位（image_extract / excel_extract / image_ocr；intent_v2 / place_order_v2 已删），
  由 `_versions.yaml` / `OTC_PROMPT_SWAP_*_VERSION` 控制、默认 0 流量
- **一个 LLM 节点 = 一个 `PromptSpec`**（`app/prompts/spec.py`，ADR 0023）：`inputs` 必须是 AgentState 字段（构造期校验）、
  `output_model` 每个字段写 `Field(description=)`（输出语义唯一真源，`.md` 不再放 JSON 骨架）、`injects` 登记 `.md` 里由代码渲染的占位符、
  `user_builder` 只拼变量。共享积木在 `blocks.py`，不要在子图复制 `_format_history`
- `[user]` 段：默认只作 Dify 原始输入形态的参照，user 消息由 `user_builder` 拼变量；**只有**当 user 含规则文本时才把规则写进
  `[user]` 段用 `{{var}}` 占位并经 `render_user()` 渲染（先例 `swap/place_order.md`），这类节点的 `[user]` 段是运行时契约

## .md 文件格式约定（4-backtick 外层 fence 才不会被内层 ``` 提前闭合）

````markdown
# 提示词标题
- **node_id**: `1755073106378`         # 来自 Dify YAML
- **model**: `qwen3-30b-a3b`

## [system]
```
<system 提示词内容，保留 {{#node.var#}} 占位符原样>
```

## [user]
```
<user 模板>
```
````

占位符 `{{#node_id.var#}}`：Dify 由引擎渲染，LangGraph 没有渲染层。代码确实注入的占位符在 `PromptSpec.injects` 登记渲染器
（先例：`close/holding_query.py`、`ticker/tools.py` 日期占位符）；
代码不注入的就是悬空规则，属零风险删除档——不要指望 LLM 把变量名当上下文。

## 字符数提示（影响延迟）

- 单请求提示词开销按调用链上各 `.md` system 字符 ÷1.6 估算 tokens；
  当前最重路径：互换图片下单 ≈ 54K tokens、平仓下单 ≈ 37K、互换文本下单 ≈ 36K（详见 `docs/prompt-maintainability-assessment.md`）
- 长提示词显著影响 P95 延迟，评估时关注延迟指标
