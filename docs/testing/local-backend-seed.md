# 本地合成身份种子与验收边界

对应 #169。`scripts/local_backend_seed.py` 向已初始化的本机隔离库导入合成群、成员、用户配置、授权各 1 行，以及贵州茅台/腾讯控股两条公共证券记录。数据在 `tests/fixtures/local_backend/identity_seed.sql`，没有真实人员、真实授权关系、密码、token 或业务订单；应用代码没有增加标的数据字典。

在现有本地配置基础上执行：

```bash
MYSQL_URI=mysql+aiomysql://root@127.0.0.1:13308/otc_goal_seed \
GOATS_BASE_URL=http://127.0.0.1:1 \
python -m scripts.local_backend_seed --apply
```

数据库须先导入与本地 Java 对应的纯 DDL；LangGraph 表使用 `sql/init.sql`。工具只接受本机 `otc_goal_` / `local_eval_` 前缀数据库和本机端口 1 的 GOATS 地址。默认只显示计划，`--apply` 执行事务；已有行不覆盖，身份/权限/证券校验有冲突则整批回滚。

Java 启动参数也必须固定 GOATS 为 `http://127.0.0.1:1`。不更改 Java 源码、配置文件、agentUrl 或 DTO。合成身份为 `local-eval-room-923` / `local-eval-user-923`，没有真实 GOATS 授权。

2026-09-23 已完成实际导入与幂等校验，并通过真实 Java 查询返回两只证券。证据在 `tmp/goal-issues/local-seed-audit.json`、`local-instrument-probe.json`、`local-goats-boundary-evidence.json`。本轮 Java 的交易对手与权限来自 GOATS；合成数据只能验证本地链路到实际 GOATS 调用的失败边界，不能宣称已通过远端权限或真实交易。

完整本地业务环境还需要 GOATS、INVEST 与 DIFY 的系统/端点配置，以及专供测试的 Dify 认证信息。去除认证字段的配置能用于失败边界验证，不能用于宣称完整业务或上线性能基线通过。共享库认证字段不进入本种子。五条完整业务流验收继续由 #133 记录。
