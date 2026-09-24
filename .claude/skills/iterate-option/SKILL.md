---
name: iterate-option
description: 期权链路按失败根因持续迭代；最小复现、TDD修复、相关用例复验，遵守用户指定测试范围。
argument-hint: '[--case case-id]'
allowed-tools: Read, Bash, Write, Edit, Grep
---

# 期权迭代流程

1. 从任务记录、已有报告或指定trace确定一个根因，区分代码缺陷与授权对手/持仓/模型配置缺失。
2. 写最小失败测试并观察RED；实现后跑GREEN及少量相关测试。用户要求轻量验证时不逐轮跑全套或全量真实回归。
3. 代码与提示词遵循根 CLAUDE.md（Codex 读生成的 AGENTS.md）及 PromptSpec 契约；自然语言仅抽候选，Code归一化，标的原文交 Java 后端识别与校验（ADR 0025），保留字段证据。
4. 专项通过后本地提交并记录SHA、用例与未验收项。禁止push/创建PR，不修改Java源码，不伪造后端响应或降低断言。
5. 需要真实业务复验时按run-eval技能，由主代理使用scripts/local_eval.py、明确case和本地服务调度。只使用 tests/fixtures/biz，不并入已退役的 unified_golden.jsonl。
6. 完成任务后继续下一项。缺少外部条件则记录证据、所需条件并推进其他独立任务；全部被阻塞时明确交接，不把未验证项标为完成。

## 判定依据

- 产品/意图错误：检查路由与原文/引用证据。
- 参数错误：比较候选、Code归一化、字段来源及最终请求，不只看回复非空。
- 后端拒绝：如实记录，核对业务数据与权限；不得改写成成功订单卡。
- 错误：检查error.node、分类、并行原因及trace；Langfuse使用当前部署配置。
- 幂等/超时：检查真实结果核对流程，写接口不得自动重试。

## 验证命令

```bash
USE_MYSQL_CHECKPOINTER=false REQUEST_IDEMPOTENCY=false ENABLE_LANGFUSE=false python -m pytest <本次专项测试文件> -q
```

当前.env显式启用持久化；纯单测以命令级覆盖隔离依赖，不能在全局fixture绕过业务路径。
