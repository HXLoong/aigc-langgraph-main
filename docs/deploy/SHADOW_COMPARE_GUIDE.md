# Shadow 双跑指南：LangGraph vs Dify

本文档说明如何用 `scripts/shadow_compare.py` 对比 LangGraph 与原 Dify 工作流的行为，
量化"LangGraph 是否能等价替代 Dify"。

---

## 一、前置条件

| 条件 | 说明 |
|------|------|
| LangGraph 服务 | 跑在 `localhost:8000` 或可达 URL |
| mock_api 或真实后端 | 跑在 `localhost:8099`（LangGraph 依赖） |
| Dify 工作流 | 部署在 Dify Cloud / 自建 Dify，对外暴露 `/v1/workflows/run` |
| Dify App API Key | 在 Dify 控制台「应用 → API 访问」获取，形如 `app-xxxxx` |
| 样本数据 | 含 `id` + `raw_content` 的 JSONL（格式见 §七；灰度期用真实流量样本） |

---

## 二、快速开始（本地 dev）

```bash
# 1) 启 LangGraph 全栈（参考 docs/training/WINDOWS_LOCAL_SETUP.md 或 HOW_TO_RUN.md）
uv run uvicorn mock_api.server:app --host 0.0.0.0 --port 8099 &
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &

# 2) 跑 shadow（不写 MySQL，明细写入 JSON 文件）
python scripts/shadow_compare.py \
    --langgraph http://localhost:8000/v1/message \
    --dify https://dify.example.com/v1/workflows/run \
    --dify-api-key app-xxxxxxxxxxxxxxxx \
    --sample sample_real_traffic.jsonl \
    --output /tmp/shadow_diff.json

# 3) 查看汇总
python -c 'import json; d=json.load(open("/tmp/shadow_diff.json")); print(d["summary"])'
```

预期输出形如：

```
[001/030] ✓ g001  lg=345ms df=412ms  
[002/030] ✗ g002  lg=287ms df=398ms  intent=lg:confirm_order/df:place_order_request
...

============================================================
  Total: 30  Equal: 27  Diff: 2  Error: 1
  差异率: 6.9%
  差异按字段: {'intent': 2}
============================================================
```

---

## 三、生产灰度场景

灰度切换期建议把 shadow 结果写入 MySQL，便于后续聚合分析：

```bash
python scripts/shadow_compare.py \
    --langgraph https://lg-canary.internal/v1/message \
    --dify https://dify-prod.internal/v1/workflows/run \
    --dify-api-key $DIFY_API_KEY \
    --sample sample_real_traffic.jsonl \
    --mysql-host mysql-prod.internal \
    --mysql-db otc_agent_business \
    --mysql-user otc_agent \
    --mysql-password "$MYSQL_PASSWORD"
```

需要在业务库提前创建表：

```sql
CREATE TABLE IF NOT EXISTS shadow_compare (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    message_id VARCHAR(64) NOT NULL,
    primary_path VARCHAR(32) NOT NULL,
    primary_result JSON,
    shadow_result JSON,
    is_equal TINYINT(1) NOT NULL DEFAULT 0,
    diff_detail JSON,
    created_at DATETIME NOT NULL,
    INDEX idx_created (created_at),
    INDEX idx_equal (is_equal)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 四、CI 集成（差异率门槛）

把 shadow 当作发布前的质量门槛：

```bash
python scripts/shadow_compare.py \
    --langgraph $LG_URL --dify $DIFY_URL \
    --dify-api-key $DIFY_API_KEY \
    --sample sample_real_traffic.jsonl \
    --fail-threshold 0.01    # 差异率 > 1% 即 CI 失败
```

`--fail-threshold` 是浮点（0.01 = 1%）。当差异率超过阈值，进程退出码为 1。

---

## 五、对比维度与归一化

shadow_compare 只对三个核心字段做语义对比：

| 字段 | 含义 | LangGraph 取值 | Dify 取值 |
|------|------|---------------|-----------|
| `product_type` | 产品分流（option/swap/option_close/unknown） | response.product_type | data.outputs.product_type |
| `intent` | 意图（按 product 分类） | response.intent | data.outputs.intent |
| `api_code` | 后端业务返回码 | response.api_code | data.outputs.api_code |

**LangGraph 响应**（`/v1/message`）：

```json
{
  "product_type": "swap",
  "intent": "place_order_request",
  "api_code": 0,
  "reply": "...",
  "trace": [...]
}
```

**Dify 工作流响应**（`/v1/workflows/run`）：

```json
{
  "task_id": "...",
  "data": {
    "status": "succeeded",
    "outputs": {
      "product_type": "swap",
      "intent": "place_order_request",
      "api_code": 0
    }
  }
}
```

如果你的 Dify 工作流 outputs 字段名不同（例如 `productType` 驼峰），改 `_normalize_dify()`。

---

## 六、差异判定原则

shadow 是**等价性验证**，不是"哪边对"的裁决。三种典型差异及处理：

| 差异类型 | 例子 | 处理方式 |
|---------|------|---------|
| 意图分类不同 | LG=`confirm_order` / Dify=`place_order_request` | 看具体 case：通常 LG 因有 quote_content 上下文判断更准 → 更新 Dify 或保留 |
| api_code 不同 | LG=0 / Dify=500 | 后端调用差异，往往是 payload 结构不同 → 检查子图 backend / 三 Client 与 Dify 工具节点 |
| 错误类型 | LG 返回正常 / Dify 超时 | 是基础设施问题，不是逻辑差异 → 重跑 |

**经验阈值**：

- 差异率 ≤ 1%：可以发布，差异通常都是边界 case
- 差异率 1%-5%：需要逐条 review 每条差异，决定要不要修
- 差异率 > 5%：先别发，找出系统性差异

---

## 七、样本格式（--sample）

每行一条 JSON，至少包含 `id` 与 `raw_content`（可带 `quote_content` / `attachments`）：

```jsonl
{"id": "s-031", "raw_content": "000001 买入5000股 限价18.12 示例对手"}
```

灰度期直接用从生产导入的真实流量样本（如 `sample_real_traffic.jsonl`）；
`tests/fixtures/categories/` 的两种方言（`send_text` / `conversation`）**不是**该格式，需先转换。

---

## 八、常见问题

**Q: 没有 Dify 实例怎么验证 LangGraph？**

A: 用 `scripts/langfuse/langfuse_eval.py --local <fixture>` 跑本地评估 — fixture 的 expected_output 就是
"我们认为正确的答案"，不依赖 Dify：

```bash
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/categories
```

**Q: Dify 返回结构和我们约定的不一样怎么办？**

A: 改 `_normalize_dify(dify_resp)` 这一个函数即可。

**Q: 跑下来差异率 30%，全是 intent 不同？**

A: 大概率是 LangGraph 的提示词跟 Dify 不同步。检查 `app/prompts/**/*.md` 与
Dify 当前生产工作流的 LLM 节点对比，必要时跑 `python scripts/export_dify_prompts.py`
重导。
