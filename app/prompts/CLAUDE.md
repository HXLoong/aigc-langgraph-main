# app/prompts · 局部约定

> 提示词管理规则见 `.claude/rules/prompt-management.md`（来源优先级 / 改写纪律 / Dify 同步 / 占位符）。
> 子目录布局见根 `CLAUDE.md` 的「项目结构」段。本文件只补**易错点 + 文件格式 + 字符数提示**。

## 易错点

- **目录名是 `option_close/`，不是 `close/`**（沿用 Dify 命名）；子图代码侧是 `app/subgraphs/close/`，两边不对称
- **`_versions.yaml`** 才是 ADR 0003 A/B 灰度的真源；不要在 Python 里写死版本
- **同目录下的非活跃 `.md` 文件**（不被 `load_prompt()` 主路径加载）：
  - `option/intent_extract.md` — ADR 0011 拆分前的旧版统一节点快照，**保留供 diff 比对**，业务代码已切到 `intent.md` + `extract_*.md`
  - `option/param_limit.md` — Dify 原始参数校验节点，当前未接线（保留资产）
  - `swap/place_order.dify_original.md` — Dify 原始版快照，对照用
  - `swap/v2/`、`ticker/tokenize_v2.md` — 灰度实验位（由 `_versions.yaml` 控制是否启用）
  - 这些文件**禁止直接删**——会破坏 ADR 0001 D5 的"重构期内可改写但需可回滚"纪律

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

占位符 `{{#node_id.var#}}` 保留原样——不要 regex 替换，会破坏 Dify 行为对齐。

## 字符数提示（影响延迟）

- `swap/place_order.md` ≈ 126K 字符 ≈ 38K tokens（Qwen3-30B 上下文上限的一半）
- 长提示词显著影响 P95 延迟，评估时关注延迟指标
