# Git 工作流

## 分支与合入

- `main` 受保护，只经 PR 合入；在主题分支上开发（如 `feature/xxx`、`fix/xxx`、`prompt/xxx`），不在 main 直接改业务子图
- agent 只做本地分支 + commit；`git push` / 创建 PR 必须等用户显式指示（根 `CLAUDE.md`「绝对禁止」P0）

## 提交信息约定

```
<type>(<scope>): <简短描述>

<可选的详细说明>

<可选的 Footer：Closes #123 等>
```

- type：`feat` / `fix` / `refactor` / `test` / `docs` / `chore` / `style` / `ci`，以及本项目专属的 `prompt`（提示词调整）
- scope：子图 `swap` / `option` / `close`；模块 `api` / `graph` / `extraction` / `prompts` / `harness` / `eval` /
  `langfuse` / `observability` / `checkpointer` / `infra` / `ci` / `test`；跨多个时用逗号（`fix(option,close)`）

**示例**：
```
feat(swap): 支持按名义本金下单的参数提取
prompt(close): 收紧平仓意图对"撤"字的判定
test(eval): 新增 2 条雪球询价的 golden case
```

## Agent 运行中的 checkpoint 纪律

适用于 AI agent（Claude Code / Codex）驱动的长任务与自驱动循环：

- **每绿即提交**：完成一个绿色里程碑（RED → GREEN → 相关测试通过）即本地 commit；checkpoint 是恢复点，不是发布
- **记录恢复点**：长任务在 `tmp/` 的任务记录里写 checkpoint 短 sha（`git rev-parse --short HEAD`），跨会话 / 换工具恢复时从最近 checkpoint 起
- **会话结束不留脏树**：要么提交、要么 `git stash` 并在任务记录说明 WIP

## PR 标题与内容语言

**强制中文**：

- PR 标题用中文（保留 `<type>(<scope>): ...` 前缀）
- PR 描述用中文小节（结构见 `.github/pull_request_template.md`：概述 / 变更内容 / 验证 / 提交检查清单 / 关联），不混用英文小节
- 代码块、链接、ADR 编号、技术词（`workflow_dispatch` / `golden case` 等）保持英文原样

```
✅ docs(adr): 精简 ADR，只保留现行决策
❌ docs: Simplify ADRs and keep current decisions only
```

## PR 检查清单

以 `.github/pull_request_template.md` 为唯一清单；提交前本地命令见 `.claude/rules/testing.md`「提交前自检」。

## 敏感文件

**绝对不提交**：`.env`、`CLAUDE.local.md`、`tmp/` 下的输出、`__pycache__/` / `.pytest_cache/`、任何含真实 API Key / Password
的文件、生产日志导出（即使脱敏过也要先 review）。多数已在 `.gitignore`，提交前仍需自查。

## 冲突解决

- 提示词文件（`app/prompts/**/*.md`）：以本仓 git 版本为准，按业务语义手工合并（ADR 0024 D1）；合并后跑对应数据集子集评估
- State / 子图代码：先读懂两边意图，不简单选一边；主题分支合入最新 main 用 merge commit，不改写他人分支历史

## 发布

发布与上线放行以 ADR 0030 D3 的评测门为准；shadow compare 只是可选对照，不是发布门。
