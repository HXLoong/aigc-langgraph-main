# Skills 使用入门：Claude Code 与 Codex 共用一套流程

> 面向：本项目所有开发者（无论用 Claude Code 还是 Codex）。读完 10 分钟能上手。
> 真源约定见根 `CLAUDE.md`「团队工具链」段；生成脚本 `scripts/sync_agents_md.py`。

---

## 1. Skill 是什么

一个 **skill** 就是一个目录里的 `SKILL.md`：顶部 YAML frontmatter 写 `name` 和 `description`，正文写"遇到这类任务时按这个流程做"。两个工具都遵循同一个开放标准（Agent Skills），所以本仓库只维护一份，另一份自动生成：

| | Claude Code | Codex |
|---|---|---|
| 仓库内技能目录 | `.claude/skills/<name>/SKILL.md`（**真源，手写**） | `.agents/skills/<name>/SKILL.md`（**生成物，禁止手改**） |
| 个人技能目录 | `~/.claude/skills/` | `~/.agents/skills/` |
| 项目指令文件 | `CLAUDE.md` + `.claude/rules/*.md`（真源） | `AGENTS.md`（生成物） |
| 显式调用 | `/name 参数` | `$name` 后接自然语言 |
| 隐式触发 | 按 `description` 自动匹配 | 按 `description` 自动匹配 |

工具启动时只读每个 skill 的 `name` + `description`，命中后才加载正文。所以 **`description` 决定它什么时候被用**，写清"使用场景"比写清"怎么做"更重要。

## 2. 本仓库现有的 skill

| skill | 用途 | Claude Code | Codex |
|---|---|---|---|
| `test-driven-development` | TDD 红绿循环（修 bug / 新功能前必走） | `/test-driven-development` | `$test-driven-development 修复 xxx` |
| `add-intent` | 在某子图新增意图（枚举 + 路由 + 提取节点 + 提示词 + 测试） | `/add-intent swap adjust_hedge` | `$add-intent 在 swap 新增 adjust_hedge` |
| `run-eval` | 通过本地 HTTP 入口评估显式 categories 用例（依赖 Java 与授权测试数据） | `/run-eval --case case-025` | `$run-eval 只跑 case-025` |
| `shadow-test` | shadow 对照工具（可选，不进任何评测门） | `/shadow-test --max-cases 20` | `$shadow-test 抽 20 条` |
| `langfuse` | 查询 / 操作 LangFuse、查文档（上游 langfuse/skills，勿手改） | `/langfuse` | `$langfuse ...` |
| `iterate-option` | 期权链路按失败根因迭代：最小复现 → TDD 修 → 相关用例复验 | `/iterate-option --case case-022` | `$iterate-option 只看 case-022` |
| `subgraph-builder` | 新增 / 重构业务子图（原 subagent） | 作为 subagent 自动派发 | `$subgraph-builder ...` |
| `test-generator` | 为节点 / 子图 / 模型生成 pytest（原 subagent） | 同上 | `$test-generator 给 holding_query 补测试` |

后两个在 Claude Code 里是 `.claude/agents/` 下的 **subagent**（独立上下文、指定工具集）；生成器同时把它们转成 Codex 同名 skill，调用时 Codex 以该角色执行。两边使用子代理都须用户明确授权（根 `CLAUDE.md`「并行实施与验证范围」）。

## 3. 怎么调用

### Claude Code

```text
/add-intent swap adjust_hedge
```

斜杠 + 名字 + 参数。`SKILL.md` 里的 `$1`、`$2` 就是按顺序传入的参数；`argument-hint` 在输入时会提示格式。不带斜杠直接描述任务，Claude 也会按 `description` 自动挑 skill。

### Codex

```text
$add-intent 在 swap 子图新增 adjust_hedge 意图
```

美元号 + 名字，后面用自然语言把参数说清（Codex 不传位置参数，生成的 `SKILL.md` 顶部有一行说明 `$1`/`$2` 对应用户给出的第 1、2 个参数）。也可以不写 `$name`，直接描述任务让 Codex 自己匹配。

### 两个工具通用的三个习惯

1. **修 bug 或加功能先走 TDD skill**，这是根 `CLAUDE.md` 核心原则 5 的强制要求。
2. **改提示词前看 `prompt-management` 规则**（Claude 自动加载 `.claude/rules/prompt-management.md`；Codex 在 `AGENTS.md` 附一里已并入）。
3. skill 正文里的命令是给 agent 执行的，你只需要给出意图和参数，不用自己敲。

## 4. 新增或修改一个 skill

只改真源 `.claude/skills/`，然后重新生成。

```bash
# 1. 新建（或修改）真源
mkdir -p .claude/skills/my-skill
$EDITOR .claude/skills/my-skill/SKILL.md

# 2. 生成 Codex 侧产物（AGENTS.md + .agents/skills/）
python scripts/sync_agents_md.py

# 3. 自检（提交前也跑这一步，不同步请重新生成后再提交）
python scripts/sync_agents_md.py --check

# 4. 一起提交
git add .claude/skills/my-skill .agents/skills/my-skill
```

`SKILL.md` 模板：

````markdown
---
name: my-skill
description: 一句话说清"什么情况下用、什么情况下不用"。这是触发依据，比正文更重要。
argument-hint: "<必填参数> [可选参数]"     # 可选；值含 [ ] 或 : 时请加引号
---

# 标题

## 参数
- `$1` = ...

## 步骤
1. 读 ...
2. 改 ...
3. 跑 `pytest tests/xxx -q` 确认
````

生成器会把 Claude 专有字段处理掉：`allowed-tools` 去掉，`argument-hint` 放进 `metadata`，`references/` 等子目录原样复制。

## 5. 常见问题

**Q：我在 Codex 里改了 `.agents/skills/xxx/SKILL.md`，为什么校验不过？**
因为它是生成物。改 `.claude/skills/xxx/SKILL.md` 再跑 `python scripts/sync_agents_md.py`。

**Q：`description` 应该写多长？**
一两句，说清场景和反场景（例："只在用户明确要求 TDD 时触发，一般 implement / fix 请求不触发"）。工具装的 skill 多了会截断长描述。

**Q：frontmatter 报 YAML 错误？**
Claude Code 解析很宽松，Codex 侧生成器做了兜底，但新写时请把含 `[`、`]`、`:` 的值加引号，例如 `argument-hint: "[--limit N]"`。

**Q：Claude 的 subagent 和 skill 有什么区别？**
subagent 在独立上下文里跑、有自己的工具白名单，适合"派出去做一件事再回来"；skill 是在当前会话里加载的流程说明。Codex 侧由生成器把 subagent 也转成同名 skill，两边共用同一份角色说明。

**Q：个人技能放哪？**
Claude Code：`~/.claude/skills/<name>/SKILL.md`；Codex：`~/.agents/skills/<name>/SKILL.md`。个人技能不进仓库，也不受生成脚本管理。

## 6. 相关文件

- 根 `CLAUDE.md`「团队工具链」段：真源与生成物的约定
- `scripts/sync_agents_md.py`：生成器（`--check` 供提交前自检）
- `.claude/rules/prompt-management.md`：改提示词必须遵守的规则（ADR 0023 + 0003）
- `.claude/skills/test-driven-development/SKILL.md`：TDD 完整流程
