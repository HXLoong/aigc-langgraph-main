# 2026-05 主分支变更记录与后续计划

> 时间窗口：2026-05-07 ~ 2026-05-09
> 来源：`git log --since="2 days ago" main`
> 目的：把这两天 main 分支上完成的工作沉淀成可追溯的文档，并梳理出下一步需要做的事项。

---

## 一、commit 时间线

| 日期 | Hash | 类型 | 标题 |
|------|------|------|------|
| 2026-05-07 | `de76868` | feat(mock) | securities-instrument 标的查询 mock，闭环脱离 VPN 依赖 |
| 2026-05-07 | `baf8ced` | feat(shadow) | 重构 shadow_compare + 扩 golden 到 30 条 + 接入指南 |
| 2026-05-07 | `cd2b605` | feat(v1) | 闭环 demo 30/30 PASS + route 引用上下文兜底 |
| 2026-05-08 | `1ea3198` | chore(dify) | 添加 Dify 工作流同步工具和 YAML 文件 |
| 2026-05-08 | `62b817d` | test(api) | 新增 GOATS 20 个接口连通性测试，支持链式调用和一键运行 |
| 2026-05-09 | `ebbf768` / `15b969a` | merge | 合入 PR #3 / PR #5 至 main |

5 个功能性 commit + 2 个 merge commit，共改动 ~18000+ 行（其中 Dify YAML 导出占大头）。

---

## 二、主要变更（按主题分组）

### 2.1 V1 闭环：脱离 VPN / 真实后端的端到端验证

**Commits**：`de76868`、`baf8ced`、`cd2b605`

**目标**：让"LangGraph 闭环可用"在零外部依赖下可验证（无 Docker / 无 LLM key / 无 Dify / 无 VPN）。

**关键改动**：

- `mock_api/server.py`：新增 `GET/POST /admin-api/integration/securities-instrument/select`，内置 17 条常用标的词典（A 股 7 + 港股 4 + 美股 4 + 期货 2），同时注册 GET 和 POST 两种方法兼容 `search_securities_instrument` 工具。这是 ticker 子图最后一处依赖内网（`172.16.8.28:8807`）的调用，至此 LangGraph 全链路可在公网/CI 环境跑通。
- `scripts/demo_closed_loop.py`（新增）：用 `InMemorySaver` + `SmartLLMMock` + Mock 后端，做 30 条 golden case 的 in-process 串测。**当前状态：30/30 PASS（100%）**，平均延迟 46ms。CI 入口：`tests/test_closed_loop.py`。
- `app/nodes/route.py`：新增两条引用上下文兜底规则
  - 1.5：`raw_content` 包含 `H-YYYYMMDD-XXXX` 互换订单号 → 走 swap
  - 3 fallback：`raw_content` 没命中关键词，但 `quote_content` 含产品关键词 → 路由到对应子图
- `tests/fixtures/golden.jsonl`：扩到 30 条，覆盖 swap / option / option_close / unknown / 优先级冲突。

**收益**：

| 维度 | 改前 | 改后 |
|------|------|------|
| pytest 通过数 | 49/49 | **117/117** |
| 闭环 demo 准确率 | 不存在 | **30/30 PASS** |
| 闭环依赖 | VPN + LLM key + 后端 | **零依赖**（in-process Mock） |

### 2.2 Shadow 双跑工具重构

**Commit**：`baf8ced`

**痛点**：旧版 `shadow_compare.py` 假设 Dify 返回扁平 body（实际是 `data.outputs.*` 嵌套）、强依赖 MySQL、缺 dry-run 与 CI 友好选项。

**关键改动**：

- 新增 `_normalize_dify()` / `_normalize_langgraph()` 适配两侧响应形状。
- MySQL 改为可选（`--mysql-host` 留空即跳过），缺 `aiomysql` 也能跑。
- 新增 `--output` JSON 输出（含 summary + 每条详情 + 归一化后字段）。
- 新增 `--dry-run` / `--max-cases` / `--fail-threshold` 三种 CI 友好选项。
- Dify 调用自动包 `inputs` 层 + 写 `Authorization: Bearer ...`。
- `docs/SHADOW_COMPARE_GUIDE.md`：完整接入指南（前置条件、本地 dev 双跑、生产灰度场景、MySQL 表结构、Tab 分析查询）。

### 2.3 Dify 工作流同步工具

**Commit**：`1ea3198`

**新增目录**：`dify/`

```
dify/
├── sync.py                 # 从内网 Dify 平台下载工作流 YAML
├── README.md
└── yaml/                   # 5 个 Dify 工作流的导出文件（只读资产）
    ├── 主干工作流.yml
    ├── 标的智能化推断和分词工具.yml
    ├── 标的相关性排序工具.yml
    ├── 场外交易-期权工具.yml
    └── 场外交易-互换工具.yml
```

**用法**：

```bash
# 通过环境变量
export DIFY_EMAIL="..." DIFY_PASSWORD="..."
python dify/sync.py                                  # 仅下载
python dify/sync.py --push                           # 下载 + 推送默认分支
python dify/sync.py --push --target-branch feature-x # 推送到指定分支
```

**与代码库的关系**：YAML 是只读资产，与 `app/prompts/` 对应。如果业务方在 Dify 上调优了提示词，先用 `dify/sync.py` 拉新版 YAML，再用 `scripts/export_dify_prompts.py` 导出 `.md` 提示词，最后跑 `scripts/eval_golden.py` 回归。

### 2.4 GOATS 20 个接口连通性测试

**Commit**：`62b817d`

**新增目录**：`tests/api/`（24 个文件，1071 行）

```
tests/api/
├── _utils.py            # 共享：签名、请求、响应校验
├── run_all.py           # 一键运行所有 20 个测试
├── README.md
├── test_01_option_rfq.py        ... test_11_option_close_withdraw_result.py  # 期权 11 个
├── test_12_trs_order.py         ... test_17_trs_replace_results.py            # 互换 6 个
├── test_18_ctpty_list.py / test_19_trading_hours.py / test_20_dify_rerank.py
└── test_gotats_endpoints.py     # 旧的总控测试，保留参考
```

**特点**：

- 链式调用（撤单测试内部包含「下单 → 查状态 → 撤单」链路）；
- 单文件可独立运行：`python tests/api/test_05_option_withdraw.py`；
- 一键运行：`python tests/api/run_all.py`；
- 仅依赖 `requests`，不与 pytest 主测试混跑（这是连通性烟雾测试，不是 LangGraph 单元测试）。

---

## 三、当前快照

### 3.1 测试矩阵

| 维度 | 命令 | 结果 |
|---|---|---|
| 单元 + 闭环 CI | `pytest tests/ -v` | **117/117 PASS** |
| 离线闭环 demo | `python scripts/demo_closed_loop.py` | **30/30 PASS（100%）** |
| 全链路集成测试 | `python tests/run_integration_test.py` | 15/15 PASS（需 mock_api + LangGraph） |
| Mock 接口端点 | `python mock_api/test_all_endpoints.py` | 32 个端点 200 OK |
| GOATS 接口连通性 | `python tests/api/run_all.py` | 20 个接口（需真实后端） |

### 3.2 外部依赖现状

| 依赖 | 改前 | 改后 |
|---|---|---|
| Java 后端 | 必须 | mock_api 替代 |
| GOATS API | 必须 | mock_api 替代 |
| 标的查询接口 | 需 VPN | mock_api 替代（2026-05-07 落地） |
| Docker（MySQL/Redis/RabbitMQ） | 必须 | 仅集成测试需要 |
| LLM API Key | 必须 | 仅集成测试需要 |
| Dify 实例 | 必须 | 不再依赖 |

---

## 四、下一步计划（按优先级）

### P0 · 灰度切换准备（本周内）

1. **Shadow 双跑接入生产采样流量**
   - 把 `scripts/shadow_compare.py` 接入生产采样脱敏后的真实流量。
   - 跑满 24 小时（`--mysql-host` 写到 `otc_agent_business.shadow_compare`）。
   - 量化指标：差异率 < 3%、字段级差异分布、P95 延迟差。
   - 见 `docs/SHADOW_COMPARE_GUIDE.md`。

2. **Option 标准询价 LLM 不稳定**
   - `extract_option` 偶将 `new_inquiry` 识别为 `unknown`（见 `docs/TEST_AND_CONNECTIVITY_STATUS.md` 1.4）。
   - 行动：扩 golden 中标准询价 case 至 ≥ 5 条，跑 `eval_golden.py`，必要时按 `prompt-management.md` 走 `_v2.md` A/B。

3. **goats 真实签名接入**
   - `app/subgraphs/ticker_tools.py:search_goats` 当前是签名示意代码。
   - 行动：联调 goats 内网鉴权 → 把 mock 替换为真实调用 → 保留 `MOCK_GOATS=true` 环境变量做回退。

### P1 · 提示词与 Dify 同步流水线（下周）

4. **从最新 Dify YAML 同步提示词到 `app/prompts/`**
   - 流程：`dify/sync.py` → `scripts/export_dify_prompts.py /tmp/new-dify /tmp/new-prompts` → `diff -r app/prompts/ /tmp/new-prompts/` → 选择性合入 → 跑 `eval_golden.py`。
   - 见 `.claude/rules/prompt-management.md`。

5. **扩 golden set 至 200+ 条**
   - 从生产日志脱敏抽取，覆盖：图片/Excel 模态、多标的批量、参与型/雪球询价、撤单 vs 改单边界、引用上下文回复。

### P2 · 工程基建（持续）

6. **企微确认卡片集成**
   - 把 `interrupt_before` 与确认卡片按钮联动（`/v1/message/confirm` 已具备恢复能力，缺的是企微侧 UI）。

7. **CI 接入**
   - 在 GitHub Actions 跑 `pytest tests/ -v` + `python scripts/demo_closed_loop.py` + `ruff check`。
   - PR 检查：差异率 < 5% 强卡口（基于 shadow output）。

8. **观测**
   - 生产开 LangSmith（`ENABLE_LANGSMITH=true`），或自建 OpenTelemetry。
   - 每个节点的 `trace` 字段写到 `node_trace` 表，便于线上排障。

### P3 · 待澄清

9. **Redis 集群配置生产化**
   - 当前文档里的 Redis 用的是单节点伪集群（`CLUSTER ADDSLOTS 0..16383`），生产是否走真集群需对齐基础设施同学。

10. **goats 库版本与依赖**
    - `pyproject.toml` 里 goats 的来源（PyPI / 私服 / git）需确认，避免 CI 拉不到。

---

## 五、文件清单（这两天新增）

```
dify/                                       # 新增目录
├── README.md
├── sync.py
└── yaml/  (5 个 .yml)

docs/
├── CHANGELOG_2026-05.md                    # 本文档（新增）
├── SHADOW_COMPARE_GUIDE.md                 # 新增（206 行）
└── TEST_AND_CONNECTIVITY_STATUS.md         # 修订

scripts/
├── demo_closed_loop.py                     # 新增（502 行）
└── shadow_compare.py                       # 重写（+283 净增）

tests/
├── api/                                    # 新增子目录（24 文件，1071 行）
├── test_closed_loop.py                     # 新增

mock_api/server.py                          # 新增 securities-instrument 端点（+91 行）
app/nodes/route.py                          # 引用上下文兜底（44 增 16 删）
.env.example                                # 标的查询 URL 切到 mock_api
tests/fixtures/golden.jsonl                 # 扩到 30 条
```

---

## 六、相关文档

- 架构总览：`docs/ARCHITECTURE.md`
- Dify 迁移：`docs/DIFY_MIGRATION.md`
- 开发指南：`docs/DEVELOPMENT.md`
- Shadow 双跑：`docs/SHADOW_COMPARE_GUIDE.md`
- 测试与联调状态：`docs/TEST_AND_CONNECTIVITY_STATUS.md`
- Dify 同步工具：`dify/README.md`
- GOATS 接口测试：`tests/api/README.md`
