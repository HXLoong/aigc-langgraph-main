# Langfuse Agent Skill 与 CLI

> 参考：[langfuse/skills](https://github.com/langfuse/skills) 仓库、[Langfuse CLI 官方文档](https://langfuse.com/docs/api-and-data-platform/features/cli)。

Langfuse 除了 WebUI，还有两条**自动化路径**。

## 两者是什么

| | Agent Skill | CLI |
|---|---|---|
| 是什么 | 给编码智能体读的操作手册，纯文档，不含执行逻辑 | 把 Langfuse API 包成命令行的执行工具 |
| 谁在用 | Claude Code、Cursor、Codex 这类智能体 | 智能体、脚本、CI，也可以人手动敲 |
| 解决什么 | 让智能体知道该**按什么步骤、什么最佳实践**操作 | 让调用方**能真的读写** Langfuse 数据 |

一句话：**Skill 是手册，CLI 是手册里用的工具。** Skill 的动作要靠 CLI 落地，所以装了 Skill 通常要保证 CLI 可用；反过来只用 CLI（写脚本、跑 CI、做批量操作）不需要 Skill。

CLI 由 Langfuse 的 OpenAPI spec 生成，每个 API 端点都有对应命令。

## 安装

两者都走 npm。先准备项目 API Key（`Project settings → API Keys`）并设为环境变量——CLI 与 SDK 共用同一套：

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"   # 按数据区域填，自托管填自己的地址
```

**CLI**

```bash
npm i -g @langfuse/cli
```

装完命令名是 `langfuse`。不想全局装就用 `npx @langfuse/cli`。

> 这个包旧名 `langfuse-cli`，内容相同，新使用请用 `@langfuse/cli`。

**Skill**

```bash
npx skills add langfuse/skills --skill "langfuse"
```

默认装到当前项目的 skills 目录；加 `--agent <agent-id>` 可指定目标智能体。

## 使用

**CLI** —— 命令格式固定为 `api <resource> <action>`。拿不准有哪些 resource 和 action，用自省命令逐层问：

```bash
langfuse api __schema                 # 列出全部 resource
langfuse api datasets --help          # datasets 支持哪些 action
langfuse api datasets list --limit 2  # 实际调用，直接返回 JSON
```

resource 覆盖 traces、observations、prompts、datasets、scores、sessions、metrics 等。不需要单独登录，直接读上面那三个环境变量。

**Skill** —— 不用你写命令，描述目标即可，智能体自己翻手册、自己调 CLI：

```text
把最近 7 天评分低于 0.5 的 trace 找出来，整理成一个 dataset
```

```text
把这个项目现在的系统提示词迁到 Langfuse 的 prompt management 里
```

覆盖查询与管理 traces / prompts / datasets / scores、查官方文档，以及一套 **judge 校准流程**——反复调整 LLM-as-a-Judge 直到它判得对。

---

人工看结果、点按钮确认仍走 WebUI，见 [WebUI 操作手册](./web-ui-operation-manual.md)；本项目已有的 Dataset 上传、Evaluator 同步、Experiment 脚本见[功能与评测链路使用指南](./workflow-guide.md)。
