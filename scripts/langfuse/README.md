# scripts/langfuse

与 Langfuse 交互的脚本。真源与推送方向见 [ADR 0014 D3](../../docs/adr/0014-langfuse-as-harness-backend.md)：
提示词 / 数据集 / 评分口径都以 git 为准，biz/intent 仍以 git 为基线；平台新标注只导出待复核快照，不自动覆盖 git，节点样本按审阅后的 Dataset 管理。
各脚本的职责见 [docs/langfuse/workflow-guide.md](../../docs/langfuse/workflow-guide.md) §7，完整参数以各脚本 `--help` 为准。

## 脚本

| 脚本 | 作用 |
|---|---|

| `node_dataset.py` | 节点标注发布、固定版本导出、HTTP 节点 Experiment |
| `upload_golden_to_langfuse.py` | fixture → Langfuse Dataset |
| `upload_prompt_to_langfuse.py` | git 提示词 → Langfuse Prompts |
| `upload_evaluators.py` | 同步 Code Evaluators 及其 Online Evaluation Rules |
| `upload_score_configs.py` | 同步人工标注用的 Score Configs 与 Annotation Queues |

## 黄金集评测入口

本目录不再提供黄金集执行脚本。统一使用 `python -m harness run`，参数及执行限制见 [测试指南](../../docs/testing/README.md)。
意图与业务均在 Python 内同步确定性判定，不等待平台 JS，不要求 Node.js。
本地追踪、最终 Score 上传和 Dataset Experiment 关联不是同一件事；当前 `run` 的完整平台结果闭环尚未接通，见 [工作计划](../../docs/work-plan.md)。

## node_dataset.py

```bash
# 发布已经人工复核的节点标注；来源 observation 和非空 expected 必需
python -m scripts.langfuse.node_dataset publish --dataset nodes/main/parse-instruction \
  --input /opt/work-file/code-tmp/aigc-langgraph-tmp/reviewed-nodes.jsonl --reviewer '<审阅者>'
# 平台标注导出为复核快照；不会覆盖 git 基线
python -m scripts.langfuse.node_dataset export --dataset nodes/main/parse-instruction \
  --out /opt/work-file/code-tmp/aigc-langgraph-tmp/node-review.json
# 安全节点通过 HTTP 回归；写节点即使平台误标 replay=true 仍然 SKIP
python -m scripts.langfuse.node_dataset run --dataset nodes/main/parse-instruction \
  --base-url http://127.0.0.1:8201 --out /opt/work-file/code-tmp/aigc-langgraph-tmp/node-experiment.json
```

`export` / `run` 可传 `--version` 固定带时区的 ISO 版本时间。无有效样本或全 SKIP 时仍为待验收。

## upload_golden_to_langfuse.py

把 fixture 上传成 Langfuse Dataset。手动模式默认源是 `tests/datasets/biz`；`--sync-all` 递归扫描整个 `tests/datasets/` 的 JSONL，以去掉扩展名的相对路径命名，例如 `biz/option_close`、`intent/option_close`。

```bash
# 同步所有现役 JSONL（每个文件一个 Dataset）
python scripts/langfuse/upload_golden_to_langfuse.py --sync-all

# 单个文件（--suite / --backend 可覆盖按路径自动判定的套件）
python scripts/langfuse/upload_golden_to_langfuse.py --dataset-name biz/option_close \
  --source tests/datasets/biz/option_close.jsonl --mode append
```

> 新数据集用 `--mode append`。默认的 `overwrite` 会先清空旧条目，而它对**还不存在**的
> 数据集会因 404 直接报错。

## upload_prompt_to_langfuse.py

推送提示词到 Langfuse 演练区。参数是 `category.name`，对应 `app/prompts/<category>/<name>.md`。

```bash
python scripts/langfuse/upload_prompt_to_langfuse.py option_close.parse_instruction --dry-run
python scripts/langfuse/upload_prompt_to_langfuse.py option_close.parse_instruction
```

> 读的是**工作区**的 `.md`（未提交的改动也会被推上去）；默认打 `staging` 标签。
> 运行时提示词始终从 git 加载，不读 Langfuse Prompts（生产开启 `USE_LANGFUSE_PROMPTS` 会直接报错）。

## upload_evaluators.py / upload_score_configs.py

把 `definitions/` 下的定义全量同步到 Langfuse。两个脚本都必须显式选 `--dry-run` 或 `--apply`。

```bash
python scripts/langfuse/upload_evaluators.py --dry-run
python scripts/langfuse/upload_evaluators.py --apply
```

`upload_score_configs.py` 先同步 `definitions/score-configs.json` 的 Score Configs，再按
`definitions/annotation-queues.json` 同步 Annotation Queues（`score_configs` 字段写名称，
脚本解析成远端 id 后绑定）。

Langfuse 只开放 queue 的 items / assignments 操作，**没有 queue 级 update 或 delete**：
绑定不一致时脚本报 `drift` 并提示人工在 UI 重建，不会自动改。

## 非入口模块

| 模块 | 作用 |
|---|---|
| `_public_api.py` | Langfuse Public API 的最小同步客户端 |
| `_definitions.py` | 读取 `definitions/` 下的资源定义 |
| `definitions/` | Evaluator 与 Score Config 的定义（`evaluators.json` / `score-configs.json`） |

## 约定

- 所有写远端的脚本**先跑 `--dry-run`**
- 需要 Langfuse 凭据的脚本从 `.env` 读 `LANGFUSE_*`；缺失时自行报错退出
- 业务逻辑在 `app/` 与 `harness/`，本目录只是入口胶水（见 [scripts/CLAUDE.md](../CLAUDE.md)）
