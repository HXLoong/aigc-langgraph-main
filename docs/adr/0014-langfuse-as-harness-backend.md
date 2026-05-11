# ADR 0014 · LangFuse 作为 Harness 工程的后台服务

- **Status**: Accepted
- **Date**: 2026-05-10
- **Deciders**: Tony

## Context

ADR 0001（Harness-first 重写）和 ADR 0002（综合运行时 Harness）定义了 Harness 的目标：开发期 / 运行期 / 调优期三位一体。落地需要一个后台服务承载：

- **Trace**：节点级 LLM 调用记录（ADR 0004 原决定 LangSmith）
- **Dataset**：Golden case 集合的 versioned 管理
- **Evaluation**：LLM-as-judge 自动评分（ADR 0005）
- **Annotation**：业务方抽检 UI（ADR 0005）

LangSmith 是 Anthropic SaaS，所有 prompt + LLM 输出（含客户企微原话、订单参数）会出境美国——**与场外衍生品业务的金融数据合规要求冲突**。这条单独就足以驱动重新选型。

LangFuse 作为开源可观测/评估平台（MIT 协议核心 + 28k+ stars + LangGraph 原生集成）满足合规要求，且功能 superset 于我们对 Harness 的需求。

## Decision

### D1 · 部署模式：Self-hosted

LangFuse 自托管在内网（Docker Compose 起 PostgreSQL + ClickHouse + LangFuse server），所有 trace、dataset、annotation 数据**不出境**。

不选 LangFuse Cloud（EU）：金融数据合规优先于运维便利。

### D2 · 取代 LangSmith，不双跑

废止 ADR 0004 中 "LangSmith 是运行时硬依赖" 的部分（见本 ADR Related 段对 0004 的修订说明）。所有 trace 走 LangFuse 单一通道。

不走"双跑过渡"：LangFuse 功能 superset，双跑徒增运维成本，无真实价值。

### D3 · 提示词管理：Git `.md` 是真理来源，LangFuse Prompts 仅作 staging 演练区

**真理来源永远是 `app/prompts/**/*.md`** —— 生产环境绝不走 LangFuse 拉提示词。

**LangFuse Prompts 仅在 staging 环境作为"灰度切换前的演练区"**，承担运维/产品在 UI 上快速试新提示词的职能。流程：

```
[运维/产品] 在 LangFuse UI 改 prompt（如 swap/intent v2）
    ↓
[代码] 在 staging 环境，load_prompt() 检查 LANGFUSE_PROMPT_OVERRIDE 环境变量
    ↓ 命中（仅 staging）
临时拉 LangFuse 的实验版 prompt 执行
    ↓
跑 harness golden set，比对基线 v1
    ↓ 通过（如 +N% 准确率）
[开发者] 运行 `python scripts/promote_langfuse_prompt.py swap.intent`
    ↓
LangFuse v2 内容自动写入 app/prompts/swap/intent_v2.md
    ↓
git commit + PR + review + merge（保留 git 审计屏障）
    ↓
生产环境按 ADR 0003 的"v1/v2 同目录"机制金丝雀切换
    ↓
v2 稳定后：删 LangFuse 上的实验版 + 走 ADR 0003 的清理纪律
```

工程支持要点：

1. **`load_prompt()` 双源支持**：
   ```python
   def load_prompt(category: str, name: str) -> Prompt:
       if env.is_staging() and env.langfuse_override_for(f"{category}.{name}"):
           return _load_from_langfuse(category, name)
       return _load_from_file(category, name)  # 默认/生产唯一路径
   ```

2. **生产硬性禁用**：`LANGFUSE_PROMPT_OVERRIDE` 在生产环境读取时直接 raise，防止误操作

3. **晋升脚本**：`scripts/promote_langfuse_prompt.py <category.name>` 拉 LangFuse 内容、按 ADR 0003 写到 `_v{N+1}.md`、提示开发者做 git commit

4. **LangFuse Prompts 的清理纪律**：晋升后 7 天内删 LangFuse 上的对应实验版（避免 staging 数据漂移污染未来实验）

不走 LangFuse Prompt Management 作为生产真理来源的理由：

- 金融审计要求提示词改动在 git PR 里被 review，DB 版本化做不到
- 提示词与代码的"加载逻辑、Pydantic 输出 schema、节点函数"是耦合演进的，必须同 commit 改动才能保证一致
- 文件 v1/v2 + git diff 是 LLM 提示词调优最自然的 review 形式
- 但完全屏蔽 LangFuse Prompts 又浪费了它的实验便利——折中方案保留 staging 演练区，是"运维灵活 + 生产严格"的平衡

### D4 · 数据流向

| 数据类型 | 写入 | 读取 |
|---------|------|------|
| Trace（节点级 LLM I/O） | LangGraph callback handler 自动写 | LangFuse UI / harness reporter API 拉 |
| Dataset（Golden case） | `tests/fixtures/*.jsonl` 同步脚本 + harness 从 trace 一键 sample | harness runner 跑回归 |
| Score（评估分数） | LLM judge job + harness differ | LangFuse UI / 报告生成 |
| Annotation（业务方标注） | 业务方在 LangFuse Annotation Queue UI | 标注同步脚本回流 jsonl |

### D5 · Harness CLI 与 LangFuse 的接入点

```
harness/
├── cli.py
│   ├── harness run <case-id|all>     # 跑 case，trace 自动写 LangFuse；本地输出 JSON 报告
│   ├── harness eval <dataset>        # 拉 LangFuse dataset 跑评估，写 score
│   ├── harness diff <run-a> <run-b>  # 比对两次 run（如 dify vs langgraph 的 shadow）
│   ├── harness sync-golden           # tests/fixtures/golden.jsonl ↔ LangFuse dataset 双向同步
│   └── harness promote-prompt <name> # 调用 scripts/promote_langfuse_prompt.py
├── langfuse_client.py                # 单例 LangFuse SDK 封装
├── runner.py / differ.py / reporter.py / golden.py
```

### D6 · 数据保留策略

| 数据 | 保留期 | 理由 |
|------|--------|------|
| Trace | 90 天 | 排错足够；防止 ClickHouse 容量爆炸 |
| Dataset | 永久 | 是 harness 的真理来源 |
| Score | 永久 | 评估历史不能丢，否则趋势分析失去基础 |
| Annotation | 永久 | 业务标注是稀缺资产 |

90 天后 trace 走 LangFuse 自带 retention policy 自动清理。

### D7 · 失败报告格式（修订 ADR 0001 D7）

D7 原设计自定义 JSON 失败报告。引入 LangFuse 后简化：

- **机器可读**：直接走 LangFuse Trace API（含完整 span 树 + 字段级 metadata），AI 工具用 LangFuse SDK 拉 trace + score
- **suspected_node / suspected_prompt**：在 harness reporter 层写薄薄一个启发式定位脚本（"diff 字段的最后写入节点"），从 LangFuse trace 读出，附在报告 metadata 里
- **人可读**：LangFuse UI 直接看 trace + diff + score，不再单独维护 markdown 报告

ADR 0001 D7 的"四个关键设计"中，1/2/3 由 LangFuse 原生提供，4（suspected_prompt 文件路径）由 harness reporter 自加 metadata。自定义 JSON 报告作为 fallback（CI 离线场景）保留。

### D8 · 安全与配置

- LangFuse 实例部署在内网 VPC，仅允许从 LangGraph FastAPI 实例 + 业务方 PC 访问
- LangFuse API Key 通过 `app.config.get_settings()` 读 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`，不硬编码
- LangFuse 的 PostgreSQL/ClickHouse 备份纳入业务库同等级别
- `ENABLE_LANGFUSE` 开关：CI / 本地 fast loop 测试可关，避免无意义的 trace 噪音

## Alternatives

### 替代 1：保留 LangSmith（ADR 0004 原决定）

- ❌ 数据出境，金融场景不可接受
- ❌ 厂商锁定，迁移成本高
- ❌ 标注 / dataset 收费，长期 TCO 高
- ❌ 国内访问稳定性差

### 替代 2：自研 Trace + Eval 系统

- ❌ 重复造轮子，1-2 人月起
- ❌ UI 体验追不上 LangFuse
- ❌ 业务方标注界面要从零做
- 价值不抵成本

### 替代 3：LangFuse Cloud（EU）

- ✅ 免运维
- ⚠️ 数据存欧盟（GDPR + SOC2），比美国 LangSmith 好
- ❌ 仍是出境，金融审计争议
- 不是不可，但 self-hosted 没有真实劣势就没必要妥协

### 替代 4：LangFuse 全功能用，Prompts 也改用 LangFuse

- ❌ 与金融审计要求冲突（提示词改动需 git review）
- ❌ 提示词与代码耦合演进，分离版本化会引入不一致

### 选择 self-hosted + 完全取代 + 提示词折中的理由

self-hosted 解决合规；取代而非双跑节省运维；提示词折中保留运维灵活性的同时守住 git 审计——是三个维度都最优的组合。

## Consequences

### 积极

- **数据合规一次解决**：所有 LLM 调用数据在内网闭环
- **Harness 后台 4 件套统一**：trace + dataset + eval + annotation 一个平台
- **业务方独立操作能力**：在 LangFuse UI 自己看 trace、做标注、试新提示词，不需要研发陪跑
- **AI 工具友好**：LangFuse 有完整 REST API，Claude Code 能直接拉 trace 做 root cause
- **演练 → 晋升流程清晰**：LangFuse Prompts 演练 + git PR 晋升，运维灵活和生产审计两全

### 消极及缓解

| 后果 | 缓解 |
|------|------|
| 多一个基础设施依赖 | Docker Compose 起 PG + ClickHouse + Server 共约 6 GB RAM；运维一次性投入 |
| 团队学习曲线 | 概念简单，1-2 天上手；M1 阶段顺带集成 |
| LangFuse 项目风险 | MIT 协议给了 fork 兜底；项目活跃度健康 |
| 与 Cursor / Claude Code 等工具的开箱集成不如 LangSmith | 通过 LangFuse REST API 自建薄层补足，半天工作量 |

## Related

### 直接修订/取代的 ADR

- **ADR 0004**（trace = LangSmith）→ trace 改用 LangFuse；本 ADR 取代 0004 中的 LangSmith 部分（保留 trace 字段设计、SQL `node_trace` 表、trace_id 贯穿等结构性约束）
- **ADR 0005**（标注平台 = LangSmith Annotation Queue）→ 改为 LangFuse Annotation Queue，其他不变（LLM judge + 业务方周抽检 + 双层分工保持）

### 不冲突但相关的 ADR

- **ADR 0001 D7**（失败报告 JSON）→ 简化为"LangFuse Trace API + 薄启发式定位层"，本 ADR D7 段说明
- **ADR 0003**（提示词文件版本化）→ 不修订，本 ADR D3 在其基础上叠加"staging 演练区"

### 资源

- LangFuse 官方文档：<https://langfuse.com/docs>
- LangFuse LangChain/LangGraph 集成：<https://langfuse.com/docs/integrations/langchain>
- 部署模板：本仓库 `infra/langfuse/docker-compose.yml`（M1 阶段创建）
