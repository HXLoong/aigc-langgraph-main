# Shadow Compare Dry-Run 模式设计（F4.1 阻塞性需求 · follow-up）

> 本 PR (#111) 完成 P0 全做的前两件（probe runner + deploy 集成），第三件 "shadow_compare 真后端 dry-run" 因涉及业务 client 改造留作下个 PR。本文档作为设计稿。

## 1. 问题

F4.1 shadow 双跑设计：

```
真实用户消息 → 同时分发到 [LangGraph, Dify] → 收集两端响应 → diff 业务字段
```

shadow_compare.py 当前实现通过 HTTP 调外部 LangGraph 服务（`--langgraph http://...`），LangGraph 实例的 .env 配置决定它是否走真后端。

**致命问题**：F4.1 期间需要观察 LangGraph 的业务输出准确性，但不能真下单：
- 用户发"互换下单 茅台 100 股" → LangGraph 走 swap.place_order 节点 → 调 `SwapClientHttpx().operate()` 真后端 → **真创建订单**
- Dify 那边只是另一条独立处理路径，不阻止 LangGraph 真下单
- 客户业务方原本以为 shadow 是"观察用"，结果系统替他真下了单 → 严重信任事故

## 2. 解决方案：LangGraph 端 DRY_RUN_BACKEND 模式

### 2.1 配置层

`.env` 新增：

```
# F4.1 Shadow 双跑期间设 true，让真后端 *.operate / *.close_order 等
# 写类调用被拦截，返回 fake CommonResult({code: 0, data: "dry-run"})。
# read 类调用（query / get / list）仍真调，保留真实数据回路。
DRY_RUN_BACKEND=false
```

### 2.2 client 层

3 个 *ClientHttpx 加 dry_run 模式：

```python
class OptionClientHttpx:
    def __init__(self, ..., dry_run: bool | None = None) -> None:
        # 默认从 env 读，可显式覆盖
        if dry_run is None:
            dry_run = os.environ.get("DRY_RUN_BACKEND", "").lower() in ("true", "1", "yes")
        self._dry_run = dry_run
    
    async def operate(self, req: ...) -> CommonResult:
        if self._dry_run:
            logger.info("DRY_RUN intercepted: option.operate type=%s", req.type)
            return CommonResult(code=0, msg="dry-run", data={"orderId": "DRY-RUN-001"})
        # ... real path
```

**关键决策**：
- `operate` / `close_order_*` 等**写类**拦截
- `query_*` / `get_*` / `list_*` / `search_*` / `get_inference_prompt` **不拦截**（read 安全）
- 拦截时返回的 fake response 让下游节点正常渲染 reply_text（业务方仍能看到 LangGraph 处理结果）

### 2.3 trace 标记

dry-run 拦截需要在 trace 中明确标记：

```python
# state["trace"] 中加一条
{
    "node": "swap.backend",
    "decision": "DRY_RUN intercepted operate type=place_order_request",
    "dry_run": True,
}
```

shadow_compare diff 时 ignore `dry_run=True` 的节点输出（业务字段照 diff）。

## 3. 安全护栏

| 层 | 护栏 |
|---|---|
| 代码 | 启动 banner 打印 `DRY_RUN_BACKEND=true` 标识，避免误配 |
| 部署 | deploy-customer.sh step2 (.env 校验) 加 advisory：F4.1 期间显式打印 dry_run 状态 |
| 监控 | metrics 新增 `otc_agent_dry_run_intercept_total{client,operation}` counter |
| 文档 | runbook §5 加 dry-run 故障处置（dry_run=true 但金丝雀=ALL → 误配警报） |

## 4. 实施步骤（下个 PR）

1. `app/config.py` 加 `dry_run_backend: bool = False` settings 字段
2. 3 个 *ClientHttpx 加 dry_run 参数 + 拦截写类方法
3. metrics 新增 dry_run_intercept counter
4. state.trace 标记 + reporter 适配
5. 单测 + 集成测试（dry_run=true 时 operate 不调真 httpx）
6. `.env.customer.template` §10/§11 增 DRY_RUN_BACKEND 字段
7. runbook §5 加 dry-run 段
8. shadow_compare.py 加 advisory：检测 LangGraph /metrics 含 dry_run_intercept > 0 → ok

## 5. 工作量估算

| 项 | 工时 |
|---|---|
| 3 client 改造 + 单测 | 1.5h |
| metrics + trace + reporter | 1h |
| config + .env + deploy 集成 | 0.5h |
| runbook + shadow_compare 适配 | 1h |
| 集成测试 + 回归 | 1h |
| **合计** | **5h** |

## 6. 替代方案（已弃）

### A. shadow_compare 自己实现拦截
放弃：shadow_compare 是 HTTP 客户端，没法拦截被测 LangGraph 内部的真 httpx 调用。

### B. LangGraph 部一份"假后端"实例
放弃：要维护两套 LangGraph 实例的 .env / 部署流，太复杂。

### C. 用 mock_api 替代真后端
放弃：shadow 的目的是观察"如果是真后端，LangGraph 会如何"——必须真后端配置但只拦写。

## 关联

- 本 PR：#111（probe runner + deploy 集成）
- 触发：用户问"真后端测试联调"评估
- 下个 PR：实施本设计
- F4.1 阶段（路线图 docs/m3-m4-roadmap.md）
