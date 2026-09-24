# scripts/langfuse

与 Langfuse 交互的脚本。真源与推送方向见 [ADR 0014 D3](../../docs/adr/0014-langfuse-as-harness-backend.md)：
提示词 / 数据集 / 评分口径都以 git 为准，本目录只做 git → Langfuse 的单向同步，不从 Langfuse 拉回。
各脚本的完整参数与使用场景见 [docs/langfuse/workflow-guide.md](../../docs/langfuse/workflow-guide.md) §7。

## 脚本

| 脚本 | 作用 |
|---|---|
| `langfuse_eval.py` | 跑数据集实验并打分（评测主入口） |
| `upload_golden_to_langfuse.py` | fixture → Langfuse Dataset |
| `upload_prompt_to_langfuse.py` | git 提示词 → Langfuse Prompts |
| `upload_evaluators.py` | 同步 Code Evaluators 及其 Online Evaluation Rules |
| `upload_score_configs.py` | 同步人工标注用的 Score Configs |

## langfuse_eval.py

跑 LangGraph，DeepSeek Judge 打分，结果写入 Langfuse。

```bash
# 从 Langfuse Dataset 跑
python scripts/langfuse/langfuse_eval.py --dataset biz/option_inquiry --ids case-022 --concurrency 1

# 从本地 fixture 跑（不走 Langfuse Dataset，可用 --fail-under 做 CI 门槛）
python scripts/langfuse/langfuse_eval.py --local tests/fixtures/intent --concurrency 3 --fail-under 0.95
```

## upload_golden_to_langfuse.py

把 fixture 上传成 Langfuse Dataset。手动模式默认源是 `tests/fixtures/biz`；`--sync-all`
递归扫描 `tests/fixtures/` 下所有 JSONL，按相对路径去掉扩展名命名（如
`biz/option_close.jsonl` → `biz/option_close`）。路径中的 `/` 会在 Langfuse 中形成文件夹。

```bash
# 同步所有现役 JSONL（每个文件一个 Dataset）
python scripts/langfuse/upload_golden_to_langfuse.py --sync-all

# 单个文件（--suite / --backend 可覆盖按路径自动判定的套件）
python scripts/langfuse/upload_golden_to_langfuse.py --dataset-name biz/option_close \
  --source tests/fixtures/biz/option_close.jsonl --mode append
```

> 新数据集用 `--mode append`。默认的 `overwrite` 会先清空旧条目，而它对**还不存在**的
> 数据集会因 404 直接报错。

## upload_prompt_to_langfuse.py

推送提示词到 Langfuse 演练区。参数是 `category.name`，对应 `app/prompts/<category>/<name>.md`。

```bash
python scripts/langfuse/upload_prompt_to_langfuse.py option_close.intent --dry-run
python scripts/langfuse/upload_prompt_to_langfuse.py option_close.intent
```

> 读的是**工作区**的 `.md`（未提交的改动也会被推上去）；默认打 `staging` 标签。
> 运行时提示词始终从 git 加载，不读 Langfuse Prompts（生产开启 `USE_LANGFUSE_PROMPTS` 会直接报错）。

## upload_evaluators.py / upload_score_configs.py

把 `definitions/` 下的定义全量同步到 Langfuse。两个脚本都必须显式选 `--dry-run` 或 `--apply`。

```bash
python scripts/langfuse/upload_evaluators.py --dry-run
python scripts/langfuse/upload_evaluators.py --apply
```

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
