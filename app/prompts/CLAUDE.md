# app/prompts · 局部约定

> 提示词管理规则见 `.claude/rules/prompt-management.md`（来源优先级 / 改写纪律 / Dify 同步 / 占位符）。
> 子目录布局见根 `CLAUDE.md` 的「项目结构」段。本文件只补**易错点 + 文件格式 + 字符数提示**。

## 易错点

- **目录名是 `option_close/`，不是 `close/`**（沿用 Dify 命名）；子图代码侧是 `app/subgraphs/close/`，两边不对称
- **`_versions.yaml`** 才是 ADR 0003 A/B 灰度的真源；不要在 Python 里写死版本
- **活跃 / 灰度 / 非活跃三态以 `_manifest.yaml` 为机器可读真源**（ADR 0022），不再在本文件手写清单。
  `python scripts/prompt_inventory.py` 打印清单，`--check` 进 CI 守四条不变量：目录 ↔ manifest 无孤儿、
  active 必有真实加载点、inactive 零引用 + 有 reason、gray（`*_v2.md`）相对 v1 无漂移
  （v1 在 v2 切出后被改动 → 必须重做 diff 并写 `drift_acknowledged`）。
  - 新增 .md → 必须登记；删 .md → 必须注销；去 LLM 化一个节点 → 把条目改成 `inactive` + reason
  - 当前 8 个 inactive 资产（`option/intent_extract`、`option/param_limit`、swap 去 LLM 化的 5 个订单号
    节点 + `swap/confirm`）的保留理由与可删条件都写在 manifest 的 `reason` 里；ADR 0001 D5
    "重构期内可改写但需可回滚"纪律仍然有效，删除前先看 reason
- **git `.md` 是唯一生产真源，Dify YAML 只是上游输入**（ADR 0022 D1，2026-09-15 拍板）：manifest 每条镜像条目有
  `dify: {file, node_id, system_sha256}`；Dify 侧更新后 `prompt_inventory.py --check` 会告警「上游有更新待人工 diff 合入」，
  合入后把 `system_sha256` 更新为新值。旧的 7 文件逐字锁定测试已退役。改 `.md` 请在该条目 `changelog` 加一行
- 5 个 `swap/*_v2.md` 灰度位现只剩 image_extract / excel_extract / image_ocr 三个（intent_v2 / place_order_v2 已删），
  由 `_versions.yaml` / `OTC_PROMPT_SWAP_*_VERSION` 控制、默认 0 流量；manifest 记录 v1 快照 sha，v1 再变必须重新 ack
- `[user]` 段：所有节点只用 `prompt.system`，user 消息由节点代码拼装，`.md` 里的 `[user]` 段仅作 Dify
  原始输入形态的参照（ADR 0022）

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

占位符 `{{#node_id.var#}}`：Dify 由引擎渲染，LangGraph 没有渲染层。代码确实注入的占位符在节点里
`system.replace(...)` 渲染并在 `_manifest.yaml` 的 `injects` 登记（先例：`close/holding_query.py`、`ticker/tools.py`）；
代码不注入的就是悬空规则（`prompt_inventory.py --strict` 列出），属零风险删除档——不要指望 LLM 把变量名当上下文。

## 字符数提示（影响延迟）

- 单请求提示词开销以 `python scripts/prompt_inventory.py` 的 system 字符 ÷1.6 估算 tokens；
  当前最重路径：互换图片下单 ≈ 54K tokens、平仓下单 ≈ 37K、互换文本下单 ≈ 36K（详见 `docs/prompt-maintainability-assessment.md`）
- 长提示词显著影响 P95 延迟，评估时关注延迟指标
