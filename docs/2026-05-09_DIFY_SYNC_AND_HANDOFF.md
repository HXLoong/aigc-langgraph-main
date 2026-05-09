# 2026-05-09 · Dify 工作流同步与后续工作交接

> **本文档目标读者**：接手后续开发的同事（实习生、新同学）
> **本次开发方式**：Claude Code（claude.ai/code）+ 人工 Review
> **分支**：`claude/update-defi-workflows-hKNTU` → 待 PR 合并到 main
> **关联文档**：`docs/CHANGELOG_2026-05.md`（月度变更）、`docs/YAML_COVERAGE_2026-05.md`（YAML 逐节点核对矩阵）

---

## 一、本次工作概览

业务方在 2026-05 又对 Dify 的 5 个工作流做了一轮调优，本次工作的目标是**把这一轮变更同步到 LangGraph 代码库**，并保持"零外部依赖闭环可跑"这一硬约束。

### 1.1 输入

```
dify/yaml/
├── 主干工作流.yml                       927KB / 77 节点 / 19 LLM
├── 标的智能化推断和分词工具.yml         77KB  / 25 节点 / 3 LLM
├── 标的相关性排序工具.yml               19KB  / 7 节点  / 1 LLM
├── 场外交易-期权工具.yml                28KB  / 8 节点  / 0 LLM
└── 场外交易-互换工具.yml                14KB  / 4 节点  / 0 LLM
```

### 1.2 产出

- **2 个 commit**（已推送到分支 `claude/update-defi-workflows-hKNTU`）
  - `72b3a9c feat(dify-sync): 同步 2026-05 最新 Dify 工作流到 LangGraph 代码`
  - `175fea3 feat(dify-sync): 补齐 5 个 YAML 的覆盖缺口（excel_extract + 模态感知提示词）`
- **23 个 LLM 提示词**全部可加载，5/5 YAML 全覆盖
- **126/126 pytest** + **30/30 闭环 demo** 通过

---

## 二、本次完成的事项（按子图分组）

### 2.1 互换（swap）

| 变更 | 触发 Dify 节点 | 落地位置 |
|---|---|---|
| 同步 `place_order` 提示词，新增 `placeOrderQuantityHand`（手） vs `placeOrderQuantity`（股）拆分 | 1776160580437 互换-节点-下单 | `app/prompts/swap/place_order.md`、`SwapOrderLeg` |
| 同步 `confirm_order` 提示词，改为提取**所有** orderId（quote_content 中可能有多个）| 1776160728475 互换-节点-确认下单 | `app/prompts/swap/confirm_order.md`、`SwapOrderIdOutput` |
| 新增 `hand_to_share` 节点：非期货标的把手数 × 每手股数 → 股数 | 1776947381378 互换-手转为股 | `app/subgraphs/swap.py:hand_to_share`、`app/prompts/swap/hand_to_share.md` |
| `extract_place_order` 改为模态感知，三种 LLM 提示词分用 | 1764752539169 / 1764841677781 | `app/subgraphs/swap.py` |
| 修复 `SwapPlaceOrderOutput.order_list` 缺 alias 导致 camelCase 测试失败 | — | `app/subgraphs/swap_models.py` |

### 2.2 期权平仓（option_close）

| 变更 | 触发 Dify 节点 | 落地位置 |
|---|---|---|
| 同步 `place_close` 提示词，新增 orderList 输入、Quick-Execution → POV25、Pattern A/B/C 隐式价量解析 | 1772602519902 请求下单和确认全部平仓参数提取 | `app/prompts/option_close/place_close.md`、`ClosePlaceOrderLeg`（新增 `closeOrderNotionalDelta` / `closeOrderPovRatio` 等字段） |
| `extract_place_close` 在调 LLM 前，先调 `query-close-orders` 拉 availableNotional 喂给提示词 | 1776755680654 获取订单信息 | `app/subgraphs/close.py:_extract_close_targets` + `OtcBackendClient.query_close_orders` |
| 新增 `CloseOrderListItem` Pydantic 模型对齐 query-close-orders 响应 | — | `app/subgraphs/close_models.py` |

### 2.3 期权（option）

| 变更 | 触发 Dify 节点 | 落地位置 |
|---|---|---|
| 把硬编码的 `OPTION_EXTRACT_PROMPT` 删掉，改为加载 `option/intent_extract.md` | 1755073106378 期权-意图识别、参数提取（Dify 已合并原本的"参数限制检查 + 意图识别"两个节点）| `app/prompts/option/intent_extract.md`、`extract_option` |

### 2.4 标的（ticker）

| 变更 | 触发 Dify 节点 | 落地位置 |
|---|---|---|
| `tokenize` 新增"市场前缀拆分"规则（美股苹果 → ["美股","苹果"]）| 1775735672603 互换-标的代码和code的拆分 | `app/prompts/ticker/tokenize.md` |
| `infer_code` 补充国际期货月份字母 + YY 格式（CLK26.NYM 等）| 1775735653728 大模型推断对应标的代码 | `app/prompts/ticker/infer_code.md` |
| `rank` 新增"代码精确匹配 vs 概念词"优先规则 | 1775820432797 大模型排序并过滤 | `app/prompts/ticker/rank.md` |

### 2.5 后端依赖

| 端点 | 状态 | mock_api |
|---|---|---|
| `/admin-api/financial-orders/query-close-orders` | **2026-05 新增** | ✓ `mock_api/server.py` |
| 其余 7 个 `/admin-api/*` | 已有 | ✓ |

整条链路保持"**脱离 AIGC / GOATS 真实后端可跑通**"。

---

## 三、改动文件清单（共 22 个）

### 提示词（11 个，按 2.1 节规则同步，**只读资产，不要手工改**）

```
app/prompts/option/intent_extract.md           [新增]
app/prompts/swap/excel_extract.md              [新增]
app/prompts/swap/hand_to_share.md              [新增]
app/prompts/swap/place_order.md                [更新]
app/prompts/swap/confirm_order.md              [更新]
app/prompts/swap/image_ocr.md                  [更新]
app/prompts/option_close/place_close.md        [更新]
app/prompts/option_close/holding_query.md      [更新]
app/prompts/ticker/tokenize.md                 [更新]
app/prompts/ticker/infer_code.md               [更新]
app/prompts/ticker/rank.md                     [更新]
```

### 业务代码（6 个）

```
app/subgraphs/swap.py            +129 增/15 改  hand_to_share + 模态感知
app/subgraphs/swap_models.py     +50  增       quantity_hand + 多 orderId
app/subgraphs/close.py           +53  增/8 改  query_close_orders 前置调用
app/subgraphs/close_models.py    +73  增/15 改 CloseOrderListItem 等
app/subgraphs/option.py          +44  增/30 改 extract_option 改为 load_prompt
app/tools/otc_backend.py         +33  增       query_close_orders 方法
```

### 测试与脚本（3 个）

```
mock_api/server.py               +29 增  query-close-orders mock 端点
scripts/demo_closed_loop.py      +1  增  query_close_orders 加入 mock client
tests/test_e2e.py                +1  增  query_close_orders 加入 mock fixture
tests/test_models.py             +57 增  多 orderId / quantity_hand 用例
```

### 文档（2 个）

```
docs/YAML_COVERAGE_2026-05.md           [新增] 5 YAML 121 节点覆盖矩阵
docs/2026-05-09_DIFY_SYNC_AND_HANDOFF.md [新增] 本文档
```

---

## 四、如何验证（30 秒上手）

```bash
# 1. 装依赖
pip install -e ".[dev]"

# 2. 单元 + 闭环测试（不需要 LLM key、不需要 Docker、不需要 VPN）
pytest tests/ -v --ignore=tests/api      # 期望 126/126 PASS
python scripts/demo_closed_loop.py        # 期望 30/30 PASS，平均 ~35ms

# 3. 加载所有提示词（确保 23 个 .md 都没有解析问题）
python -c "
from app.prompts import load_prompt
for cat, name in [
    ('swap', 'intent'), ('swap', 'place_order'), ('swap', 'confirm_order'),
    ('swap', 'cancel_order'), ('swap', 'confirm_cancel'), ('swap', 'confirm_modify'),
    ('swap', 'query_order'), ('swap', 'image_ocr'), ('swap', 'image_extract'),
    ('swap', 'excel_extract'), ('swap', 'hand_to_share'),
    ('option_close', 'intent'), ('option_close', 'place_close'),
    ('option_close', 'holding_query'), ('option_close', 'confirm_close'),
    ('option_close', 'cancel_close'), ('option_close', 'confirm_cancel'),
    ('option_close', 'query_status'),
    ('option', 'intent_extract'),
    ('ticker', 'tokenize'), ('ticker', 'completeness'),
    ('ticker', 'infer_code'), ('ticker', 'rank'),
]:
    p = load_prompt(cat, name)
    assert p.system, f'{cat}/{name} 空'
print('23/23 OK')
"

# 4. 启 mock 后端，全链路联调
uv run uvicorn mock_api.server:app --port 8099 &
python tests/run_integration_test.py     # 15/15 PASS
```

---

## 五、后续工作安排（按优先级）

### P0 · 发布前必须完成（建议本周内）

#### 5.1 Shadow 双跑生产灰度

把本次代码接到 `scripts/shadow_compare.py`，在生产采样脱敏流量上跑满 24 小时。

- **入门成本**：低，工具已就绪
- **关键指标**：
  - 字段级差异率 < 3%（特别盯 `placeOrderQuantityHand` / `closeOrderNotionalDelta` / `closeOrderPovRatio` 三个新字段）
  - P95 延迟差 < 20%
- **产出**：`/tmp/shadow_diff_20260516.json` + 一封简报邮件
- **见**：`docs/SHADOW_COMPARE_GUIDE.md`

#### 5.2 扩 Golden Set，覆盖本次新增能力

`tests/fixtures/golden.jsonl` 当前 30 条，本次新增的核心场景**没有覆盖**：

| 场景 | 建议条数 | 难度 |
|---|---|---|
| 互换"手"下单（A股 `100手` / 港股 `4手` / 期货 `2手` 三种品种）| 3 | 低 |
| 互换 confirm_order 多 orderId（quote 中含 2~3 单）| 2 | 低 |
| 期权平仓 Quick-Execution（"要快"、"尽快成交"、"跟量"）| 3 | 中 |
| 期权平仓 Pattern A（`21.6平300万`）/ B（`3w 50000`）/ C（`平50% 21.6`）| 3 | 中 |
| 期权平仓"留X万其余全平"（remainder target）| 2 | 中 |
| 标的"美股苹果"/"港股通"前缀拆分用例 | 2 | 低 |

**做法**：
1. 翻 `tests/fixtures/golden.jsonl` 末尾，模仿前面格式追加（至少 15 条）
2. 跑 `python scripts/eval_golden.py tests/fixtures/golden.jsonl`，准确率不低于 95%
3. 提 PR

**入门成本**：低，主要是写测试数据。

#### 5.3 单元测试补齐

下面三块本次没补单测，先补再发布：

```python
# 1. tests/test_swap_hand_to_share.py（新建）
# 测 _is_future / _shares_per_hand / hand_to_share 节点
#   - 期货透传：CU2609.SHF 输入 hand=2 → quantity 仍为 None（不换算）
#   - A股 100/手：000858.SZ 输入 hand=10 → quantity=1000
#   - 港股查表：0700.HK 输入 hand=4 → quantity=400
#   - 港股未命中：0941.HK 默认 100 → quantity=400
#   - 美股 1/手：AAPL.O 输入 hand=10 → quantity=10

# 2. tests/test_close_query_orders.py（新建）
# 测 _extract_close_targets 正则与 query_close_orders 调用
#   - 输入 "平 CO-20260428-AAAA0001" → order_ids=["CO-..."]
#   - 输入 "OPT-20260428-X1 平一半" → contract_codes=["OPT-..."]
#   - mock query_close_orders 返回 availableNotional=5000000 时的拼接

# 3. tests/test_option_intent_extract.py（新建）
# 验证 option/intent_extract.md 加载、长度 > 50K
# 验证 extract_option 能产出 OptionExtractOutput
```

**入门成本**：中（需要熟悉 Mock LLM 套路，参考 `tests/test_e2e.py:mock_backend`）。

### P1 · 工程优化（建议下周）

#### 5.4 拆分 option/intent_extract.md 到 v2 形态

当前 `option/intent_extract.md` 是 57K 字符的巨型 prompt（合并了 Dify 6 个意图的所有逻辑）。
按 `app/prompts/swap/v2/_base.md` 的成功经验拆成 `_base.md` + `new_inquiry.md` + `place_order.md` + …，
通过 `compose_prompt()` 组装。**预期收益**：单次调用 token 减半，P95 降 1~2 秒。

入门成本：高（需要理解 prompt 结构 + A/B 测试 + golden set 验证）。
**详见 `.claude/rules/prompt-management.md` 的"修改工作流"章节。**

#### 5.5 完善 query_close_orders 链路

当前 `close.py:_extract_close_targets` 只用正则抓 CO- / OPT- ID。生产场景中：
- 用户可能引用机器人的 `quote_content`（含完整订单详情）
- 用户可能说"全部"指代上次询价的所有订单

需要把 quote_content 解析也接入 ID 提取，并在 mock 后端返回更真实的 availableNotional。

入门成本：中。

#### 5.6 wired image/excel 路径已经做了，但需要 e2e 测试

虽然 `extract_place_order` 已经按 modality 选用提示词，但 e2e 测试 (`tests/test_e2e.py`) 没有
覆盖 image/excel 路径（缺 mock VL / openpyxl）。建议补 2 条 e2e。

入门成本：中（mock VL 模型有点 tricky）。

### P2 · 长期改进

#### 5.7 把 Dify 拉取 + 提示词同步整成一个脚本

现在做 Dify 同步要跑：
```bash
python dify/sync.py                                       # 拉 YAML
python scripts/export_dify_prompts.py dify/yaml/ /tmp/    # 导出 .md
diff -r app/prompts/ /tmp/...                             # 手工 diff
# 选择性 cp 合入
python scripts/eval_golden.py ...                         # 回归
```

可以做一个 `scripts/sync_prompts.py` 一站式脚本：
- 自动找 diff
- 给每个差异打"小改/大改/重构"标签
- 大改的提示用户手工 review 后再合入
- 自动跑 eval

入门成本：高，但收益高（每次 Dify 调优都能复用）。

#### 5.8 CI 接入

`.github/workflows/ci.yml`（暂无）：
```yaml
- pytest tests/ -v --ignore=tests/api
- python scripts/demo_closed_loop.py
- ruff check app/ tests/
- 提示词加载冒烟测试（参考 §四第 3 步）
- shadow compare 差异率卡口（< 5% 才能合并到 main）
```

入门成本：低（写 yaml），但要协调有没有 GitHub Actions runner。

---

## 六、Claude Code 开发流程建议

本次工作完全在 Claude Code 中完成（参考 commit footer 的 `claude.ai/code/session_*` 链接）。
对于后续来接手的同事，建议按下面流程做：

### 6.1 起步

```bash
# 1. 在仓库根目录起 Claude Code
cd ~/aigc-langgraph
claude

# 2. 让 Claude 先读这份文档 + CLAUDE.md
> 读 docs/2026-05-09_DIFY_SYNC_AND_HANDOFF.md 和 CLAUDE.md，告诉我下一步该做什么
```

### 6.2 选定一个 P0 任务，让 Claude 帮你做

以"5.2 扩 Golden Set"为例：

```
> 我要做 docs/2026-05-09_*.md 里 §5.2 的任务，先帮我看一下 tests/fixtures/golden.jsonl
> 的格式，然后给我列出"互换手下单 3 条 + confirm_order 多单 2 条 + 平仓 Quick-Execution 3 条"
> 共 8 条 case 的草稿，但先不要写文件——我 review 后再让你写。
```

> Claude Code 的最佳实践是**先列计划，再让 Claude 动手**。`/plan` 命令也可以触发计划模式。

### 6.3 用 subagent 做并行任务

仓库里有几个项目专属的 subagent（在 `.claude/agents/` 下）：

- `subgraph-builder` — 新增/修改业务子图
- `prompt-migrator` — 从 Dify YAML 单独迁移一个提示词
- `test-generator` — 生成单元测试
- `dify-reviewer` — 审查 LangGraph 代码是否与 Dify 一致

例如做 5.3 单测时：

```
> 用 test-generator agent 给 app/subgraphs/swap.py:hand_to_share 函数
> 写一份完整的 pytest 单元测试，覆盖期货 / A股 / 港股 / 美股 / 边界 5 种情况
```

### 6.4 用 skill 做高频流程

`/sync-dify-prompts` 是配套 skill，专做提示词批量同步。
`/shadow-test` 是 shadow 双跑入口。
直接 `> /sync-dify-prompts` 即可触发。

### 6.5 提交规范

参考 `.claude/rules/git-workflow.md`。Claude Code 默认会按规范生成 commit message。
**关键**：让 Claude commit 之前一定要自己 `git diff` review 一遍，特别是 `app/prompts/**/*.md`
的改动——这些是只读资产，原则上只能从 Dify 同步，不能手工改。

### 6.6 PR 自查清单

提 PR 前过一遍：

- [ ] `pytest tests/ -v --ignore=tests/api` 全通
- [ ] `python scripts/demo_closed_loop.py` 30/30 PASS
- [ ] `ruff check app/ tests/`（你新增的文件至少要干净）
- [ ] 改了提示词加载 → 跑了 `eval_golden.py`，准确率不低于上一版
- [ ] 新增了 LLM 节点 → golden set 至少加了 2 条 case
- [ ] commit message 用中文 + Conventional Commits 格式

---

## 七、常见问题 FAQ

### Q1：我能直接改 `app/prompts/**/*.md` 吗？

**不能**。这些是从 Dify 原封导出的生产资产。要改：

1. 先在 Dify 上调
2. 用 `python dify/sync.py` 拉新版 YAML
3. 用 `python scripts/export_dify_prompts.py` 导出 `.md`
4. `diff` + 选择性合入 `app/prompts/`
5. 跑 golden set 回归

### Q2：本次新增的 `option/intent_extract.md` 字符数 57K，会不会太长？

会。这是 P1 任务 `5.4` 要解决的事。短期没事（Qwen 235b-128k 撑得住），
但 P95 延迟会 +1~2 秒，shadow 跑出来就能看到。

### Q3：`hand_to_share` 节点用纯 Python 替代 Dify 的 LLM 调用，会不会偏离 Dify 行为？

这是受控的简化：
- Dify 用外部 kimi-k2.5 做单笔换算
- 我们用查表（A股 100、港股查 `_HK_LOT_SIZE`、美股 1、期货透传）
- 期货用后缀判断（`.SHF` / `.NYM` / ...），与 Dify 提示词的硬约束语义一致
- shadow 跑出来如果差异率 < 1%，就稳

如果发现 shadow 差异率高，回退方案：在 `app/subgraphs/swap.py:hand_to_share` 内开一个
`USE_LLM = os.environ.get("HAND_TO_SHARE_USE_LLM") == "true"` 开关，走真实 LLM。

### Q4：`query_close_orders` 失败时怎么办？

`OtcBackendClient.query_close_orders` 已经做了降级（HTTP 失败 → 返回 `[]`）。
返回 `[]` 后，提示词的 `orderList` 字段为空，LLM 会按"无 availableNotional"逻辑走，
平仓金额字段为 null，后续节点根据 `error` 兜底回复用户。

### Q5：闭环 demo 30/30 PASS，是不是就一定能上生产？

**不是**。闭环 demo 只能保证**架构和路由对**，不能保证**提示词输出和 Dify 完全一致**。
真正能拍板上生产的是 Shadow 双跑 24 小时差异率 < 3%。**这是 P0 任务**。

---

## 八、紧急联系

- 提示词业务问题：找业务方（Dify 工作流的 owner）
- LangGraph 框架问题：看 `docs/ARCHITECTURE.md` + `.claude/rules/langgraph-patterns.md`
- 测试相关：看 `.claude/rules/testing.md`
- 部署问题：看 `docs/DEVELOPMENT.md` + `docs/WINDOWS_LOCAL_SETUP.md`
- Claude Code 用法：`> /help` 在会话里直接问

祝顺利接手 🎯
