---
name: run-eval
description: 通过本地 HTTP 入口评估显式 categories 用例，保存字段差异与报告；全量仅在用户要求时运行。
metadata:
  source: .claude/skills/run-eval/SKILL.md
  argument_hint: '[--case case-id] [--limit N] [--out dir]'
---

> 自动生成自 `.claude/skills/run-eval/SKILL.md`（python scripts/sync_agents_md.py），禁止手改。

# 本地业务回归

## 入口与边界

使用 scripts/local_eval.py，经 HTTP 调本地 /v1/workflows/run，并准备 Java 消息与真实授权上下文。
应用服务与数据库只用 localhost/127.0.0.1；Java 源码不修改。数据库读取 MYSQL_URI，初始化为 sql/init.sql；不存在独立 Compose mysql 服务。
显式数据源 tests/fixtures/categories（条数以 harness.golden.load_golden 实时统计为准）；不并入 unified。保留全部业务断言与真实后端响应。

## 执行

1. 读取用户指定的测试范围。若用户保留最终统一测试，默认仅做离线专项；不要自动启动真实回归。
2. 真实回归由主代理统一调度：检查本地 /health /ready、MYSQL_URI、授权 EVAL_USER_ID/EVAL_ROOM_ID 和模型能力。脚本会预检模型并拒绝远程应用目标。
3. 用少量明确用例验证；失败先归类为代码、数据/权限、模型或环境。外部阻塞记录后继续独立工作，不弱化断言。

```bash
python scripts/local_eval.py --base-url http://127.0.0.1:8201 --data tests/fixtures/categories --case case-025 --concurrency 1 --out tmp/eval
# 用户启动最终验收时再去掉 --case；全量不是每次修复的默认动作。
```

## 证据

输出目录下 manifest.json、cases.jsonl、summary.json、report.md、message_ids.json。
记录提交号、用例范围、PASS/FAIL/REJECTED、失败节点与字段差异、P50/P95/P99；小样本不能证明全量准确率或性能达标。
Langfuse 使用当前配置的部署，不固定 Cloud 地址；保留 trace_id/链接。报告与恢复点留 tmp，不提交原始日志或密钥。
