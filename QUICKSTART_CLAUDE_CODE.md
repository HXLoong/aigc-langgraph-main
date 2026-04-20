# Claude Code 快速上手

面向 otc-agent 项目的 Claude Code 实操指南。**你只需要看这一份就能开始工作。**

---

## 第一步：安装 Claude Code

```bash
# 需要 Node.js 18+
npm install -g @anthropic-ai/claude-code

# 验证
claude --version         # 应显示 v2.1.x 或更新
```

首次运行会提示登录（Anthropic 账号）。选择你使用的 plan（Pro / Team / Enterprise）。

---

## 第二步：在项目根启动 Claude Code

```bash
cd otc-agent       # 必须在项目根（有 CLAUDE.md 的那一级）
claude              # 启动交互式 session
```

启动时 Claude Code 会自动加载：
- `CLAUDE.md` （项目 memory）
- `.claude/rules/*.md` （规则文件）
- `.claude/agents/*.md` （4 个专家 agent）
- `.claude/skills/**/SKILL.md` （4 个工作流 skill）
- `.claude/settings.json` （权限配置）

**确认加载成功**：在 Claude Code 里输入 `/memory`，应该看到 CLAUDE.md 被列出。

---

## 第三步：理解你有哪些工具

### 4 个 Subagents（Claude 会自动委派，也可手动召唤）

| Agent | 何时用 | 怎么用 |
|---|---|---|
| `prompt-migrator` | 业务给了新 Dify YAML 要迁移 | "使用 prompt-migrator 把这个 yaml 里的 xxx 节点迁移过来" |
| `test-generator` | 写完代码要补测试 | "让 test-generator 为这个新节点生成测试" |
| `subgraph-builder` | 要新建/改业务子图 | "请 subgraph-builder 帮我为新的 XXX 产品加子图" |
| `dify-reviewer` | 发布前最终审查 | "用 dify-reviewer 审一下我们的 swap 子图跟 Dify 对齐情况" |

**也可以用 `/agents` 命令交互式查看和调用。**

### 4 个 Slash Commands / Skills

| 命令 | 场景 |
|---|---|
| `/migrate-prompt <yaml> <node-title>` | 单个提示词迁移 |
| `/add-intent <product> <intent>` | 新增一个意图 |
| `/shadow-test` | 跑 LangGraph vs Dify 双跑对比 |
| `/sync-dify-prompts <dir>` | 批量同步 Dify 提示词变更 |

---

## 第四步：5 个常用实战场景

### 场景 1 · 业务给了新 Dify YAML，要迁移一个新节点

```
你：业务刚在 Dify 加了"互换-图表化询价"意图，yaml 我放在 /tmp/new.yml，节点标题是"互换-图表询价"

Claude Code：（会自动调用 prompt-migrator）
- 读 .claude/agents/prompt-migrator.md
- 读 yaml，列出节点
- 汇报归类建议：swap/graph_inquiry.md
- 等你确认 → 生成 .md + Pydantic 模型 + 节点函数 + 测试
```

### 场景 2 · 新增一个业务意图（比如互换"套保对冲"）

```
你：/add-intent swap adjust_hedge

Claude Code：
- 先问你 5 个问题（业务含义、后端接口、字段...）
- 等你答完 → 改 swap_models.py / swap.py
- 调用 prompt-migrator 或询问是否手写提示词
- 调用 test-generator 补测试
- 跑 pytest 验证
```

### 场景 3 · 有个 bug，先写复现测试

```
你：客户发"CO-20260101-XYZ12345 平" 但我们识别成了 swap 而不是 option_close

Claude Code：
- 读 app/nodes/route.py
- 意识到正则 OPTION_CLOSE_PATTERN 只匹配 [0-9A-F]，XYZ 是字母，错误！
- 让 test-generator 先写一个失败的回归测试
- 修 route.py
- 重跑测试确认通过
```

### 场景 4 · 发布前对齐检查

```
你：我们准备把 swap 子图切到 10% 金丝雀，先 shadow compare 一下

Claude Code：
- 用 /shadow-test 跑一遍 golden set
- 分析 diff_detail，归类差异
- 若一致率 ≥ 99%：建议继续金丝雀
- 若 < 99%：调 dify-reviewer 做根因分析
```

### 场景 5 · 日常：改个小 bug + 加测试

```
你：extract_order_id 在 quote_content 为 None 时会崩溃

Claude Code：
- Grep 查 extract_order_id
- 看到直接 str(None) 导致的问题
- 加一行 guard
- 让 test-generator 补一个 None quote_content 的测试
- 跑 pytest 确认
```

---

## 第五步：日常工作流

```
1. 打开终端，cd otc-agent
2. claude 启动 session
3. 描述你要做的事（中文自然语言即可）
4. 观察 Claude 的计划，必要时修正
5. 每次操作前会提示权限（settings.json 里已允许的自动跳过）
6. 完成后让 Claude 跑 `pytest tests/ -v` 确认

结束工作：
- Ctrl+D 退出（会话自动保存）
- 下次 claude 进来能 /resume 回到上次
```

---

## 实用技巧

### 上下文管理

```
/clear            开始新任务时用（清空对话历史，但保留 CLAUDE.md）
/compact          上下文快满时用（总结历史，节省 token）
/memory           查看/编辑当前加载的 memory
/model sonnet     切换模型（路由任务用 haiku 更快；架构决策用 opus 更好）
```

### 只读 + 查看差异（安全模式）

```bash
claude --permission-mode plan    # 只读模式，不能改代码，适合探索/排查
```

### 用 `@file` 引用文件

在对话里直接引用文件内容，不用让 Claude 自己搜：
```
帮我优化 @app/subgraphs/swap.py 的 classify_intent 节点
```

### 并行多任务（worktree 隔离）

```bash
# 在独立 worktree 里做一个大改动，不影响主工作区
claude -w feature-new-product
```

### 查费用

```
/cost             当前 session 已花多少（token + 钱）
```

---

## 可能遇到的坑

### Q: Claude 每次启动都重新读提示词文件，很慢？
A: 正常。但 `app/prompts/swap/place_order.md` 133K 字符只是**运行时**才被 `load_prompt()` 加载给 LLM，**不会**进 Claude Code 自己的上下文。Claude Code 启动时只读 CLAUDE.md + .claude/rules/，总共不到 1000 行。

### Q: Claude Code 问我权限，很烦？
A: 把你经常做的操作加到 `.claude/settings.json` 的 `allow` 列表。当前已经允许了 pytest / docker / git 常用操作。

### Q: Claude 改了代码但破坏了测试，怎么快速回滚？
A: Claude Code 有自动 checkpoint，输入 `/rewind` 回到上一步。或用 git：`git diff` 看改了什么，`git checkout .` 回滚。

### Q: 我不想让 Claude 动某些敏感文件？
A: 在 `.claude/settings.json` 的 `permissions.deny` 列表加路径模式。

### Q: 多人团队用，如何同步配置？
A: `.claude/` 目录（除 `settings.local.json`）**提交到 git**。个人偏好放 `CLAUDE.local.md`（已在 .gitignore）或 `.claude/settings.local.json`。

### Q: Claude 建议的代码我不满意，想改 prompt？
A: 三个层次调优：
1. **全局规则不够清晰** → 改 `.claude/rules/xxx.md`
2. **特定 agent 行为不对** → 改 `.claude/agents/xxx.md` 的 system prompt
3. **某个 skill 流程不对** → 改 `.claude/skills/xxx/SKILL.md`

---

## 和 Claude.ai（网页版）对话的关键区别

| 对比项 | Claude.ai | Claude Code |
|---|---|---|
| 访问文件系统 | 只能上传文件 | 直接读写你的项目 |
| 跑命令 | 不行 | 能跑 bash、pytest、git |
| 长期记忆 | 单个 Project 内 | CLAUDE.md 永久持久 |
| Agent 编排 | 单 Claude | 多 subagent 并行 |
| 适合场景 | 头脑风暴、写作、单文件改 | 真正的编码工作 |

**建议**：
- **探索阶段** / **需求梳理** / **架构讨论** → Claude.ai（比如你和我这段对话）
- **实际编码** / **跑测试** / **合并代码** → Claude Code（本地终端）

---

## 安全告警

Claude Code 有能力执行 bash 命令。即使有 `settings.json` 的白名单，也请：

1. **生产凭证绝不放在代码或 .env 里**：用 vault / k8s secret
2. **不要让 Claude 直连生产数据库**：用只读账号或本地 docker
3. **敏感操作（prod 部署、db migration）必须手动 review**
4. **Code review 不能省**：Claude 的 PR 需要人类工程师批准

---

## 延伸阅读

- [Claude Code 官方文档](https://docs.claude.com/en/docs/claude-code/overview)
- [Subagents 指南](https://code.claude.com/docs/en/sub-agents)
- [项目内其他文档](docs/)
  - [架构](docs/ARCHITECTURE.md)
  - [开发指南](docs/DEVELOPMENT.md)
  - [Dify 迁移](docs/DIFY_MIGRATION.md)
  - [常见问题](docs/TROUBLESHOOTING.md)

---

准备好了就 `cd otc-agent && claude`，开始用 AI 结对编程。
