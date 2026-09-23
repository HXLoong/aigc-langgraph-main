# Git 文件自动同步到 Langfuse

仓库中的测试用例和提示词由 Git 管理。相关 PR 合并到 `main` 后，GitHub Actions 会把它们同步到 Langfuse；也可以在 Actions 页面手动运行。两个同步任务彼此独立。

| 同步任务 | 读取哪些文件 | 同步到 Langfuse |
|---|---|---|
| `langfuse-dataset-sync` | `tests/fixtures/intent/*.jsonl`、`tests/fixtures/categories/*.jsonl` | 一个 JSONL 文件对应一个 Dataset |
| `langfuse-prompt-sync` | `app/prompts/option/*.md`、`option_close/*.md`、`swap/*.md` | Chat Prompt，标签为 `staging` |

这里只扫描所列目录的**顶层文件**。`tests/fixtures/nodes/` 是本地节点测试数据，不会上传。两个任务运行时都检出最新的 `main`，因此上传的是主分支内容。

## 数据集会怎样更新

- 名称由文件名决定：`intent/option.jsonl` → `intent_option`；`categories/golden_option_close_case.jsonl` → `golden_option_close_case`。
- 上传前先检查所有文件。每条用例使用固定的 Item ID：`<数据集名>:<用例 ID>`。
- 每次运行都会按这个 ID 上传或更新已有 Item。所有文件上传成功后，脚本会把远端多出的 `ACTIVE` Item 标记为 `ARCHIVED`；上传阶段失败时不会开始归档。
- 删除整个本地文件、或把文件移出扫描范围，不会自动删除或归档远端 Dataset。以前上传过的 `nodes/` 数据集也不会被清理。

数据集任务只同步测试数据，不会运行 Experiment 或自动评分。

## 提示词会怎样更新

- 名称由目录名和文件名拼成：`option_close/intent.md` → `option_close_intent`；`swap/intent_v2.md` → `swap_intent_v2`。`_v2.md` 是独立名称。
- `[system]` 原样上传；有 `[user]` 就使用文件中的内容，没有则补一个含 `{{send_text}}` 的实验用 user 模板。批量同步始终创建 Chat Prompt。
- 脚本读取远端 `staging` 版本比较内容。相同就跳过；首次上传会创建；内容不同会创建新版本，并把 `staging` 标签移到新版本。Langfuse 网页上改过的 `staging` 草稿也会被 Git 内容覆盖，历史版本保留。
- 删除本地 `.md` 不会自动删除远端 Prompt。批量同步只处理 `staging`；生产运行仍从 Git 读取提示词，修改提示词仍须经过 PR 评审。

## 在 GitHub 网页上运行

1. 先确保两个 workflow 文件已随 PR 合并到目标仓库的 `main`：`.github/workflows/langfuse-dataset-sync.yml` 和 `.github/workflows/langfuse-prompt-sync.yml`。仅把提交推到个人分支，不会让目标仓库的 `main` 开始同步。
2. 在目标仓库的 **Settings → Secrets and variables → Actions** 配置：变量 `LANGFUSE_BASE_URL`（例如 `https://us.cloud.langfuse.com`）；Secrets `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`。再设置变量 `LANGFUSE_TIMEOUT=60`（秒），供数据集任务使用。
3. PR 合并到 `main` 且改动涉及上述文件、对应上传脚本或 workflow 文件时，任务自动运行。数据集任务也会响应 `harness/golden.py` 的改动。也可在 **Actions → langfuse-dataset-sync / langfuse-prompt-sync → Run workflow** 选择 `main` 手动运行。
4. 查看运行日志是否成功。数据集到 Langfuse 的 **Datasets** 核对名称和 Items；提示词到 **Prompts** 核对名称、内容和 `staging` 标签。提示词日志中的 `created`、`updated`、`skipped` 分别表示新建、生成新版、内容未变。

两个 workflow 都使用 Python 3.11 和 Langfuse SDK `4.15.0`，单次任务最长运行 30 分钟。`LANGFUSE_TIMEOUT` 控制数据集任务的单次 SDK 请求超时，与 30 分钟的任务上限不同。

## 先在本地预览

在仓库根目录的 PowerShell 中，使用已安装项目依赖的 `.venv`：

```powershell
.\.venv\Scripts\python.exe scripts/langfuse/upload_golden_to_langfuse.py --sync-all --dry-run
.\.venv\Scripts\python.exe scripts/langfuse/upload_prompt_to_langfuse.py --sync-all --dry-run
```

`--dry-run` 只检查本地文件并列出将同步的对象，不连接 Langfuse，也无法判断哪些远端内容会被跳过或更新。确认列表后，用同一环境加载 `.env` 再执行真实同步：

```powershell
.\.venv\Scripts\python.exe -m dotenv run -- .\.venv\Scripts\python.exe scripts/langfuse/upload_golden_to_langfuse.py --sync-all
.\.venv\Scripts\python.exe -m dotenv run -- .\.venv\Scripts\python.exe scripts/langfuse/upload_prompt_to_langfuse.py --sync-all
```

`.env` 需包含 `LANGFUSE_BASE_URL`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`；数据集请求可额外设置 `LANGFUSE_TIMEOUT=60`。本地执行会真实写入 Langfuse，请先确认连接的是目标项目。

详细的字段映射和手动单文件命令见 [Langfuse 功能与评测链路使用指南](./workflow-guide.md)。本功能分别由提交 `3259cd9`（数据集同步）、`eae2334`（提示词同步）、`d77bc69`（排除节点数据并配置超时）引入。
