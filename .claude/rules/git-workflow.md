# Git 工作流

## 分支策略

```
main               ← 生产，受保护，只接 PR
├── develop        ← 集成测试分支
└── feature/xxx    ← 业务功能分支
    fix/xxx        ← bug 修复
    chore/xxx      ← 杂项（依赖升级、文档等）
    prompt/xxx     ← 提示词调优（特殊分支类型）
```

## 提交信息约定

```
<type>(<scope>): <简短描述>

<可选的详细说明>

<可选的 Footer：Closes #123 等>
```

type:
- `feat` 新功能
- `fix` bug 修复
- `refactor` 重构（不改外部行为）
- `test` 加测试
- `docs` 文档
- `chore` 杂项
- `prompt` 提示词调整（本项目专属）

scope:
- `swap` / `option` / `close` / `ticker` 对应子图
- `api` / `graph` / `checkpointer` / `prompts`
- `infra` / `test` / `ci`

**示例**：
```
feat(swap): 支持按名义本金下单的参数提取
fix(ticker): 修复期货合约"YYMM"格式误入结果的 bug
prompt(close): 更新平仓意图识别提示词到 Dify v2.3
test(e2e): 新增 2 条雪球询价的 golden case
```

## PR 标题与内容语言

**强制中文**：

- PR 标题必须用中文（仍保留 `<type>(<scope>): ...` 前缀约定）
- PR 描述（body）必须用中文，含中文小节标题（如 ## 概述 / ## 变更内容 / ## 验证 / ## 关联）
- 不要混用英文小节（如 `## Summary` / `## Test plan`）—— 统一中文
- 代码块、链接、ADR 编号、技术词（`workflow_dispatch` / `golden case` 等）保持英文原样
- Commit message 沿用现有 type 约定，正文 OK 用中文（已有先例）

理由：团队 review 主语种为中文，PR 是业务方与开发的协作界面，混语种会拖慢理解。

**示例**：

```
✅ docs(roadmap): M3/M4 路线图 + 分工 SOP
✅ feat(swap): 支持按名义本金下单的参数提取
❌ docs: Add M3/M4 roadmap and team assignment SOP
```

## PR 检查清单

提交 PR 前（让 Claude Code 帮你逐条检查）：

- [ ] `pytest tests/ -v` 全部通过
- [ ] `ruff check app/ tests/` 零警告
- [ ] 如果改了提示词加载：跑 `python scripts/eval_golden.py`，准确率不低于上一版
- [ ] 如果新增节点/意图：golden set 加了 case
- [ ] 如果改了 State：`make_initial_state()` 同步更新
- [ ] 如果改了 pyproject.toml 依赖：说明原因
- [ ] 没有硬编码 secret
- [ ] 中文变更说明（供国内团队 review）

## 敏感文件

**绝对不提交**：
- `.env`（环境变量）
- `CLAUDE.local.md`（个人偏好）
- `/tmp/` 下任何输出
- `__pycache__/`、`.pytest_cache/`
- 任何含真实 API Key / Password 的文件
- 生产日志导出（即使脱敏过也要先 review）

这些在 `.gitignore` 里，但偶尔需要手动 double-check。

## Rebase vs Merge

- feature → develop：**rebase** 保持线性历史
- develop → main：**merge commit**（保留 feature 边界）
- 同一 feature 分支内部：小步提交 OK，合并前 `git rebase -i` squash 成干净 commits

## 冲突解决

提示词文件（`app/prompts/**/*.md`）冲突：
- **永远选 Dify 原始版本**，不要手工 merge
- 若是两个 PR 同时更新提示词：重新跑一次 `export_dify_prompts.py`

State / 子图代码冲突：
- 先读懂两个 PR 的意图，不要简单选一边
- 必要时把两个 feature 都 rebase 到最新 main 再合

## Tag & Release

- Tag 格式：`v0.1.0`, `v0.2.0-rc1`
- 每个 release 必须有 CHANGELOG 条目
- 生产发布前必须跑 shadow compare 至少 24 小时
