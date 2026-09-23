# Langfuse Workshop 学习指南

> 面向学习者路径。原文：<https://langfuse.com/workshop/learner>
> 上游仓库：<https://github.com/langfuse/langfuse-workshop>

## 课程是什么

Langfuse 官方的**分步实操课**，建立在一个小型 TypeScript 示例应用上：**Dad IT Support Agent**。Dad 打开网页问 iPhone 问题，机器人 **Specs** 给分步指引；底层就是一个普通的 OpenAI tool-calling loop 加两个本地工具。

课程用 Langfuse 把整条 AI 工程闭环走一遍：

```text
tracing → prompt management → monitoring → dataset → experiments → evaluation
```

走完这套课，你能独立跑通「trace → 评测 → 对比改动」的完整闭环，并把同一套做法搬到自己项目上。

> ⚠️ 请使用 **Langfuse Cloud**，这样才有课程描述的最新功能。自托管实例版本可能较旧，与课程内容对不上。

## 模块

### 00 · Setup（`checkpoint/00-setup`）

**目标**：应用在本地跑起来，OpenAI 与 Langfuse 凭据就位。这一课**不写任何埋点代码**。

**做什么**：拿 key → 装 CLI 与 skill → 配 `.env` → 装依赖跑起来。

```bash
git clone https://github.com/langfuse/langfuse-workshop.git
cd langfuse-workshop
git checkout checkpoint/00-setup

# 装 Langfuse CLI 与 skill（课程原文写的是旧包名 langfuse-cli）
npm install -g @langfuse/cli
npx skills add langfuse/skills --skill "langfuse"

cp .env.example .env     # 填下面 4 个键，其余默认值不动
npm install
npm run dev
```

> 上面装的 CLI 和 skill 分别是什么、各自解决什么问题、装完怎么用（自省命令、让智能体驱动的说法），见 [Agent Skill 与 CLI](./agent-skill-and-cli.md)。

`.env` 需要填：

```dotenv
OPENAI_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

**怎么验证**：`3333`（客户端）与 `8787`（API 服务）都在监听；`/api/health` 返回真实响应；浏览器显示 Specs 的问候而不是报错；点一个建议问题能拿到真实的 iPhone 回答。

> **前置条件**：Node.js `^20.19.0 || >=22.12.0`，用 `node -v` 确认。这条有个容易误判的坑——Vite 的平台二进制是 optional dependency，**Node 版本不够时 npm 会静默跳过它、不报错**，`npm install` 看着成功，问题要到 `npm run dev` 起不来时才暴露。装完才升级 Node 的话，重跑 `npm ci` 把跳过的二进制补回来。

> **排查**：`3333` 打不开时，把 `npm run dev` 输出往回翻到 `[dev:client]` 行。`concurrently` 会让 API 服务在 Vite 崩了之后继续跑，终端看着还活着；此时访问 `127.0.0.1:8787/` 返回 `ENOENT ... dist/index.html`，那只是因为没做生产构建，**不代表真正的原因**。`[dev:client]` 里出现 `Cannot find native binding` 才是 Node 版本问题。

### 01 · Base App（`checkpoint/01-base-app`）

> 你在 `00-setup` 里已经 clone 了仓库、checkout 了应用，基座应用就在同一个 checkout 里。所以这一章**没有任何东西要构建**——只是先熟悉一下，tracing 从 `02-tracing` 才开始。

**应用在做什么**

- 用户就是 Dad 本人，Specs（agent）直接和他聊他的 iPhone。
- 一个 OpenAI tool-calling loop，两个本地工具（`get_support_context`、`search_help_library`）。
- system prompt 由 `src/server/support-agent.ts` 在本地渲染。**还没有任何 Langfuse**。

![Specs 如何处理一张工单——一个 agent、两个工具、一个模型，每一跳都是 trace 里的一次 observation](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/specs_illustration.png)

**代码看哪里**

| 文件 | 内容 |
|---|---|
| `src/client/App.tsx` | 聊天 UI + 侧栏面板 |
| `src/server/index.ts` | Express 路由 |
| `src/server/support-agent.ts` | tool-calling loop（`02-tracing` 要给它埋点）+ system prompt 模板 |
| `src/server/tools.ts` | 工具定义与 `executeTool(...)` |
| `src/server/support-data.ts` | Dad 的固定上下文 + 帮助库 |

### 02 · Tracing（`checkpoint/02-tracing`）

**起点**

```bash
git checkout checkpoint/02-tracing
```

这是 tracing 这一步的白板——代码和 `checkpoint/01-base-app` 完全一样，还没有任何 Langfuse 接线。Langfuse 的包已经在 `package.json` 里，没跑过就先 `npm install`。确认 `.env` 里有 `OPENAI_API_KEY` 和两个 Langfuse key。

**为什么要 trace**

Tracing 按发生顺序记录 agent 的每一步——每次模型调用、每次工具调用、进去的输入和回来的输出。它把 agent 从黑盒变成事后可以打开检查的东西：答案错了，你能指出**是哪一步**错的，而不是靠猜。

想看更宏观的动机，见 [Academy 的 tracing 课](https://langfuse.com/academy/tracing)；想看技术细节（SDK 选项、OpenTelemetry 内部机制、span 属性），见 [tracing 文档](https://langfuse.com/docs/tracing)。

**目标**

Dad 问一句「怎么开蓝牙」时，agent 并不是只打一次 OpenAI。它背后先问 OpenAI 该做什么，调 `get_support_context` 取 Dad 的 iPhone 配置，再问一次 OpenAI，调 `search_help_library` 查蓝牙步骤，最后再问一次 OpenAI 产出编号答案。**这些今天全都看不见。**

这一章的目标是让每一步都在 Langfuse 里可见——一次聊天轮次变成**一条嵌套 trace**，agent run、OpenAI generation、两次工具调用都按顺序记下来。

![Spec 的分步处理流程](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/tracing/process_illustration.png)

我们分三步搭出这条 trace，和 agent 的结构一一对应：

1. **First trace** —— 先把 OpenAI generation 本身记下来。
2. **Nested traces** —— 把 generation 归到一个「每轮次一个 agent run」下面。
3. **Recording tool calls** —— 让每次工具调用成为自己的 observation。

#### Step 1 —— First trace

先给 OpenAI 调用本身加上可观测性，看清输入输出是什么，以及花了多少成本、token 和时间。改两处就够。

**`src/server/index.ts`**

在文件靠前的位置启动 Langfuse 的 span processor：

```ts
import { NodeSDK } from "@opentelemetry/sdk-node";
import { LangfuseSpanProcessor } from "@langfuse/otel";

new NodeSDK({ spanProcessors: [new LangfuseSpanProcessor()] }).start();
```

这个 processor 从 Node 进程环境里读 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`。

**`src/server/support-agent.ts`**

加 import：

```ts
import { observeOpenAI } from "@langfuse/openai";
```

然后**在创建 OpenAI client 的地方包一层**。在 `runSupportConversation` 里找到这行：

```ts
const openai = new OpenAI({ apiKey: env.openaiApiKey });
```

改成：

```ts
const openai = observeOpenAI(new OpenAI({ apiKey: env.openaiApiKey }));
```

这就是全部改动。没有工厂函数，也不用另建一个裸 client——`observeOpenAI` 就在调用点就地包一层，下面的 `openai.chat.completions.create(...)` 从此每次调用都会发出 trace。

**验证**：`npm run dev`，问一个问题，刷新 Langfuse——每次 OpenAI 调用应该出现一条 generation，带 prompt、响应、token 和延迟。此时每条 generation 还是各自独立的顶层 trace，下一步解决这个。

![Step 1 之后的 Langfuse Traces 视图——每个聊天轮次都是独立的 openai-chat-completion generation](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/tracing/02-tracing-step-1.png)

#### Step 2 —— Nested traces

为了给 generation 提供上下文，我们把它们归到「每轮次一个 agent run」下面。在 `src/server/support-agent.ts` 改三处，**不动任何函数体**。

**1. 加 import：**

```ts
import { observe } from "@langfuse/tracing";
```

**2. 把现有函数降级。** 找到：

```ts
export async function runSupportConversation(request: ChatRequest): Promise<ChatResponse> {
```

去掉 `export` 并改名：

```ts
async function runSupportConversationInner(request: ChatRequest): Promise<ChatResponse> {
```

函数体保持不变。

**3. 在文件底部加上包装后的 export：**

```ts
export const runSupportConversation = observe(runSupportConversationInner, {
  name: "dad-it-support-chat-turn",
  asType: "agent"
});
```

`index.ts` 仍然用同样的方式 import `runSupportConversation`。`observe(...)` 会自动把函数入参捕获为 trace input，把返回值捕获为 trace output。

**验证**：一次聊天轮次现在应该显示为**一条** `dad-it-support-chat-turn` observation，OpenAI generation 嵌套在它下面。

![Step 2 之后的 trace 树——一个 dad-it-support-chat-turn agent 根，OpenAI generation 作为子节点](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/tracing/02-tracing-step-2.png)

#### Step 3 —— Recording tool calls

OpenAI 的 generation 已经在它的 `tool_calls` 输出里提到了工具调用，但**工具实际执行**这件事没有任何 observation——看不到进去什么、出来什么。同样的 `observe(...)` 模式可以套到每个工具上。

**`src/server/tools.ts`**

加 import，并把两个观察过的 helper 放在 `executeTool` 上面；然后**用下面的版本替换现有的 `executeTool`**，让 switch 调这两个包装过的 helper，而不是就地干活。`TOOL_DEFINITIONS` 不动。

```ts
import { observe } from "@langfuse/tracing";

const getSupportContextTool = observe(
  async () => {
    const context = getSupportContext();

    return {
      ok: true,
      context: {
        id: context.id,
        label: context.label,
        devices: context.devices,
        deviceSummary: context.deviceSummary,
        responseStyle: context.responseStyle,
        scopeHighlights: context.scopeHighlights,
        notableApps: context.notableApps
      }
    };
  },
  { name: "get_support_context", asType: "tool" }
);

const searchHelpLibraryTool = observe(
  async (input: { question: string }) => {
    const guides = searchGuides(input.question);

    return {
      ok: true,
      results: guides.map((guide) => ({
        id: guide.id,
        title: guide.title,
        summary: guide.summary,
        steps: guide.steps,
        caution: guide.caution ?? null
      }))
    };
  },
  { name: "search_help_library", asType: "tool" }
);

export async function executeTool(name: string, input: Record<string, unknown>): Promise<ToolResult> {
  switch (name) {
    case "get_support_context":
      return getSupportContextTool();

    case "search_help_library":
      return searchHelpLibraryTool({ question: String(input.question ?? "") });

    default:
      return { ok: false, error: `Unsupported tool: ${name}` };
  }
}
```

如果 `npm run dev` 报 `Multiple exports with the same name "executeTool"`，说明原来的 `executeTool` 还在文件更下面。删掉它，只留上面这版。

![Step 3 之后的完整 trace——dad-it-support-chat-turn（agent）下面，OpenAI generation 与 get_support_context、search_help_library 两个工具 observation 并列](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/tracing/02-tracing-step-3.png)

**怎么验证你做到了**

- 单次用户轮次在 Langfuse 里产生**一条** trace。
- 根 observation：`dad-it-support-chat-turn`（类型 `agent`）。
- 子 generation 来自 `observeOpenAI(...)`，带 prompt、响应、token、延迟。
- 子工具 observation：`get_support_context`、`search_help_library`。
- 根的 input 是聊天请求，根的 output 是聊天响应。

**小结**

同一个模式，不同的 observation 类型，概念一样：`observe(fn, { asType })` 包住一个函数，发出一个带指定名字和类型的 span；`observeOpenAI(client)` 就是针对 OpenAI SDK 的专用版本。

想按 Langfuse 最佳实践更省事地加丰富 tracing，可以用 [**Langfuse skill**](https://github.com/langfuse/skills)（`/langfuse`）——它把这套推荐模式直接套到你的代码库，不用一个个手搓包装。这份 walkthrough 存在的意义，是让你明白 skill 底下在做什么。

`observeOpenAI` 包的是官方 OpenAI SDK，底层等同于 Langfuse 对 [OpenAI JS 的自动埋点](https://langfuse.com/integrations/model-providers/openai-js)。如果你用的是别的 SDK（Anthropic、Vercel AI SDK、自己的 HTTP client），[集成目录](https://langfuse.com/integrations)里有对应的包装或自动埋点指南。

**附录 · User 与 Session ID**

上面的 walkthrough 已经能得到干净的 parent → generation → tool 结构。团队接下来通常想做的是**按用户和按会话切分 trace**——调出「这个用户跟 agent 的全部对话」或「昨天上午那一整段多轮会话」。

现场 walkthrough 为了简单跳过了这一步，但 tracing 之后的 checkpoint 里已经包含它，这样后续章节能直接用 Users / Sessions 视图，不用再加一次代码改动。细节见 Langfuse 文档的 [Sessions](https://langfuse.com/docs/observability/features/sessions) 和 [Users](https://langfuse.com/docs/observability/features/users)。

简而言之：

```ts
import { propagateAttributes } from "@langfuse/tracing";

return propagateAttributes(
  {
    userId: request.userId ?? `workshop-${context.id}`,
    sessionId: request.sessionId,
    tags: ["langfuse-workshop", "dad-it-support"]
  },
  async () => {
    // ...同一套 tool-calling loop...
  }
);
```

`propagateAttributes(...)` 块内的所有东西——包括 `observeOpenAI` 发出的全部子 span——都会自动带上 `userId`、`sessionId` 和 tags。这些属性一到位，Langfuse 的 **Users** 视图、**Sessions** 视图和 tag 过滤就都亮了。

### 03 · Prompt Management（`checkpoint/03-prompt-management`）

**起点**

```bash
git checkout checkpoint/03-prompt-management
```

你现在有一个能跑、且已埋点的应用。system prompt 是 `src/server/support-agent.ts` 里的一个常量 `SYSTEM_PROMPT`，直接当 system 消息用。

这一章把它搬进 Langfuse，让它有版本、能在 UI 里编辑，并在请求时取回。本地那个常量留在文件里，作为 Langfuse 取不到时的回退。

确认 `.env` 有：

```bash
LANGFUSE_PROMPT_NAME=dad-it-support-agent
LANGFUSE_PROMPT_LABEL=production
```

**为什么要管理 prompt**

把 system prompt 放在代码里，意味着每次改 prompt 都是一次代码改动：提 PR、评审、构建、部署。用 Langfuse 的 prompt management，prompt 住在 Langfuse 里——有版本、有标签、能在 UI 里改——应用在请求时取回。于是非工程同学也能迭代 prompt，改动不再绑在发布周期上，而且每个版本都留存、并和它产出的 trace 关联。

详见 [Langfuse prompt 文档](https://langfuse.com/docs/prompt-management/overview)。

**两个方向**

提示词管理是**双向**的，本课两个 Step 正好各走一个方向：

| 方向 | 做什么 | 本课位置 | 用到的能力 |
| --- | --- | --- | --- |
| **代码 → Langfuse** | 把代码里的提示词发布上去，成为一份有版本的副本 | Step 1 | `langfuse.prompt.create(...)`，即 `npm run prompt:publish` |
| **Langfuse → 应用** | 请求时按标签取回最新版本 | Step 2 | `langfuse.prompt.get(name)` |

官方文档把它写成两选一：*"You can either create a prompt from scratch in the UI or import existing prompts from your application."*

值得注意的是官方**推荐**「UI 编辑 + 运行时拉取」这条路径，理由不是技术优劣，而是分工现实——改提示词的人（产品、业务专家）和管部署的人（工程）通常不是同一批人。提示词放在代码里，改一次文案就要走完 PR、评审、构建、部署。官方还强调这条路**不加延迟**：提示词由 SDK 在客户端缓存，取回"as fast as reading from memory"。

**目标**

两步：

1. **把 system prompt 发布到 Langfuse**，让那里有一份有版本的副本。
2. **在请求时取回**，并把每次 OpenAI generation 关联到产生它的那个版本。

#### Step 1 —— 发布 prompt（在 Langfuse UI 里）

最直接的方式是在 UI 里手动添加——这也是你团队以后每次迭代都会用的流程。

1. 在 Langfuse 里打开 **Prompts → New prompt**。
2. **Name** 填 `dad-it-support-agent`（和 `.env` 里的 `LANGFUSE_PROMPT_NAME` 一致）。
3. **Type** 选 `text`。
4. **Paste** 把 `src/server/support-agent.ts` 里 `SYSTEM_PROMPT` 的内容粘进去。
5. **Label** 给这个版本打 `production`（和 `.env` 里的 `LANGFUSE_PROMPT_LABEL` 一致）。
6. **Save**。

![在 Langfuse 里创建 dad-it-support-agent prompt](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/prompt-management/03-prompt-management-new-prompt-form.png)

> 💡 另一种做法：走上面表里的**代码 → Langfuse** 方向。`scripts/publish-prompt.ts` 会把 `SYSTEM_PROMPT` 常量推到 Langfuse（`npm run prompt:publish`），结果一样。

#### Step 2 —— 从 Langfuse 取回 prompt

**加 import**（`src/server/support-agent.ts`）：

```ts
import { LangfuseClient } from "@langfuse/client";
```

**在模块作用域构造 client：**

```ts
const langfuse = new LangfuseClient();
```

**加一个 `getPrompt` helper**，从 Langfuse 取；任何失败都返回 `null`，好让聊天回退到本地的 `SYSTEM_PROMPT`：

```ts
async function getPrompt() {
  try { return await langfuse.prompt.get(env.langfusePromptName); }
  catch { return null; }
}
```

**在 `runSupportConversation` 里用它**——先取，取回 null 就回退到本地常量：

```ts
const langfusePrompt = await getPrompt();
const systemPrompt = langfusePrompt?.prompt ?? SYSTEM_PROMPT;
```

**把 `systemPrompt` 作为 system 消息发出去。** 往下几行的 transcript 里找到这行：

```ts
{ role: "system", content: SYSTEM_PROMPT },
```

改成：

```ts
{ role: "system", content: systemPrompt },
```

不改这行，模型收到的仍然是本地常量——下一步里的 Prompt 徽章照样会出现，但在 Langfuse 里编辑 prompt 对回答没有任何影响。

**把 `langfusePrompt` 传给已有的 `observeOpenAI` 调用**，让 generation 关联到已发布的 prompt 版本——只在我们确实拿到的时候传：

```ts
const openai = observeOpenAI(
  new OpenAI({ apiKey: env.openaiApiKey }),
  langfusePrompt ? { langfusePrompt } : undefined
);
```

三点值得注意：

- `observeOpenAI(new OpenAI(...))` 这个调用本身没变——还是 02 里那个就地包装，只是多了一个可选第二参数携带 `langfusePrompt`。
- 本地 `SYSTEM_PROMPT` 常量留在文件里作为回退。Langfuse 配错或 prompt 还没发布时，聊天照常工作，只是那一轮不带 Prompt 徽章。
- 把 `langfusePrompt` 传进 `observeOpenAI`，正是让这个 client 下每次 generation 都带上 **Prompt** 徽章、指回确切已发布版本的原因。

**验证**

```bash
npm run dev
```

问一个问题，然后在 Langfuse 里：

- 打开 trace，点那条 OpenAI generation。它应该显示一个 **Prompt** 徽章，链接到 `dad-it-support-agent` 你发布的那个版本。
- 在 `dad-it-support-agent` 的 Prompts 视图里往下翻到 "Used in"，你的 trace 会出现在那里。

![带 Prompt 徽章的 openai-chat-completion trace](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/prompt-management/03-prompt-management-prompt-badge.png)

**小结**

Prompt management 是闭合「trace ↔ prompt」这条环的东西。每个 prompt 版本都留存，每次 generation 都知道自己是哪个版本产出的，你可以脱离代码发布来迭代 prompt。

想按 Langfuse 最佳实践更省事地接上 prompt management，用 [**Langfuse skill**](https://github.com/langfuse/skills)（`/langfuse`）——它把这套推荐模式套到你的代码库，不用一件件手搓。这份 walkthrough 存在的意义是让你看到 skill 底下在做什么。

### 04 · Monitoring（`checkpoint/04-monitoring`）

**起点**

```bash
git checkout checkpoint/04-monitoring
```

你有一个已埋点、可选接了 Langfuse prompt 的应用。每一轮聊天都会作为一条嵌套 trace 落到 Langfuse。

如果你跳过了模块 3、但想用 prompt management，先跑这条把 prompt 发布上去：

```bash
npm run prompt:publish
```

**为什么要监控 AI 应用**

生产环境里 AI 应用会产生大量 trace，多数没问题。值得找的是少数——漂移的回答、agent 根本不该处理的请求、随时间变化的模式。监控就是让你不用逐条读也能抓住这些信号。

更宏观的背景见 [Academy 的 monitoring 课](https://langfuse.com/academy/monitoring)。

**目标**

监控的目标是找出**对「你的」AI 应用**值得知道的事。对 Specs，我们挑了两个事件作为起点：

- **用户不认同** —— Dad 反驳（"不对，没这个菜单"）。要么 agent 给的步骤错了，要么应用暴露了能力边界。
- **全大写抱怨** —— Dad 写类似 "THIS STILL ISNT WORKING"。不是每条全大写都是愤怒，但它是个廉价、确定性的信号，说明这段对话可能需要注意。

监控还有一层「质量追踪」——某个指标的平均分随时间变化。我们建议**先做信号检测**：追踪总体质量，最好等你和团队对「质量在这个场景里到底指什么」有了明确看法之后再做，而形成这个看法最快的方式，就是去看那些出乎意料的 trace。

这一步**不需要改任何代码**。`02-tracing` 出来的 trace 形状已经带齐了这些监控需要的东西：agent observation 有完整对话和最终答案，每条 OpenAI generation 有 system prompt 和同一个消息数组。

#### Step 0 —— 配好 Langfuse 的评估模型（暂时不用 LLM judge）

本章前两个监控用的是 LLM-as-a-judge 模板。Langfuse 从你项目里的 LLM Connection 发起这些 judge 调用，所以先把它配好。

项目已有默认评估模型的话，跳过这步直接进 Step 1。

1. 在 Langfuse 打开 **Project Settings → LLM Connections**。
2. 点 **Add new LLM Connection**。
3. 选 OpenAI，给连接起个名，把你的 OpenAI API key 贴进 secret 字段。
4. 保存连接。
5. 默认评估模型在创建 evaluator 时设定：项目还没有的话，**Set up evaluator** 向导会在它的 Set up LLM connection 这一步要求你先选，才能继续。届时选那个 OpenAI 连接和一个支持结构化输出的模型（如 `openai / gpt-4.1`）再保存。设好之后它会显示在 Evaluators 页顶部的 **Default model**，之后也能改。

> key 只放在 Langfuse 的 secret 字段里，不要贴进 workshop 的共享笔记或记录。

#### Step 1 —— 接上前两个 judge 类监控（暂时不用）

Langfuse 内置了 **User Disagreement** 和 **Out-of-Scope Request** 两个已发布模板，都是 LLM-as-a-judge evaluator，从 observation 里读变量。两个模板的目标对象不同：

- **User Disagreement** 需要对话历史，所以瞄准根 observation `dad-it-support-chat-turn`（类型 Agent）。
- **Out-of-Scope Request** 需要 system prompt，所以瞄准最后那条 OpenAI generation。只有 generation 的 input 带 system message；agent 的 input 是浏览器发来的聊天请求，里面只有 Dad 的消息。

**User Disagreement** 的操作：

1. 打开 **Evaluators → New Evaluator**，在 **Template Gallery** 里选 **Detect User Disagreement**。
2. 右侧选 trace 根作为 sample observation（通常已经预选好）。我们要的就是类型为 Agent 的根 observation，也就是整条 trace 的 input/output 记录处。

   ![在 evaluator 设置面板里把 trace 根选为 sample observation](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/select-sample-observation.png)

   > **提示**：把鼠标悬停在筛选条上的筛选项会显示各自过滤掉了什么。也可以用 "Ask AI" 来配筛选。

3. 通过 UI 选择器把模板变量映射到 agent observation 的 **Input**：

   | 模板变量 | 对象字段 | JsonMapping |
   | --- | --- | --- |
   | `{{conversation_history}}` | `Input` | All messages |
   | `{{last_user_message}}` | `Input` | Last message |

   ![把对话历史变量映射到全部 input 消息](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/user-disagreement-conversation-history-mapping.png)

   ![把最后一条用户消息变量映射到 input 的最后一条消息](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/user-disagreement-last-user-message-mapping.png)

4. 在右侧面板可以对选中的 sample observation 试跑一次这个 evaluator。

   ![在选中的 sample observation 上试跑 User Disagreement evaluator](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/user-disagreement-test-evaluator.png)

5. 最后点 **Create evaluator**。接下来的界面会显示每周大致成本估算，并能设采样率。点 execute，你的第一个 evaluator 就跑起来了。

   ![用配好的筛选条件对后续 observation 执行已保存的 evaluator](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/user-disagreement-execute-evaluator.png)

#### Step 2 —— 加一个针对全大写抱怨的 code evaluator

上面的监控需要语义判断，所以用 LLM-as-a-judge；这个不需要。我们只要一个廉价的确定性检查：用户消息里有没有一长串大写字母，暗示他可能聊得不顺心。

Code evaluator 正适合这种模式：不调模型、不用设计 prompt，就是一条在实时 observation 上跑的简单规则。

1. 打开 **Evaluators → New Evaluator**，选 **Detect User Frustration (ALL CAPS)**。你会看到一个预置好的 code evaluator，它瞄准 observation 的 Input，检查一条消息里是否超过 70% 是大写字母。
2. 瞄准和上面 disagreement 监控**同一个根 agent observation**：

   ![给用户挫败感 code evaluator 选同一个根 observation](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/user-frustration-target-root-observation.png)

3. 对 evaluator 跑一次测试。
4. 点 **Create Evaluator**，再点 execute。

这个 evaluator **不需要** Step 0 配的评估模型，因为它是纯 TypeScript 代码跑在 Langfuse 沙箱里，不是 LLM judge。

**验证**

```bash
npm run dev
```

发四轮应该分别点亮一个监控的对话：

1. **不认同** —— 先问个正常问题，然后回 "No, that menu isn't there"
2. **全大写** —— "THIS STILL ISNT WORKING"

在 Langfuse 里等 evaluator 跑完（几秒后刷新），然后按 evaluator 分数排序 trace。范围外、不认同、全大写的 trace 应该浮到顶部。

![用户不认同示例](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/user-disagrees-example.png)

![ALL-CAPS evaluator 在一条 trace 上标出愤怒的用户消息](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/monitoring/all-caps-example.png)

用户不认同是高信号事件。用户对 agent 刚给出的答案提出异议时，几乎一定有什么出错了——工具结果错、上下文缺失、指令和他实际的 iPhone 对不上。这些是你最该先读的 trace，也是 `05-dataset` 最好的候选用例。

全大写信号则刻意做得更粗。它不是在断言用户肯定生气了，只是一个廉价、确定性的线索，说明对话可能在跑偏。所以它适合当「先看这些」的监控，和更丰富的不认同、范围外 judge 配合使用。

**灌生产流量，看监控真的触发**

手打四轮能证明接线通了。但监控的价值在**量**上——所以现在灌一批真实感的生产数据，看看会发生什么。

```bash
npm run langfuse:seed:otel:no-scores
```

它把一份真实的「Dad IT 支持」流量快照——外加少量合成的边界用例（范围外提问、全大写消息、以及 "no, that menu isn't there" 式的不认同）——重放进你 Langfuse 项目的 `production` 环境。它复用 `.env` 里已有的 Langfuse key，并把所有时间戳平移，让最新一条 trace 落在「现在」。

> ⚠️ 这个 seed **不是幂等的**。OpenTelemetry 每次运行都会生成新的 trace ID，重跑会让数据翻倍。只跑一次；需要干净状态就先去 Langfuse 里删掉上一次的 seed trace 再灌。

现在打开 **Tracing**，筛到 `production` 环境，过几秒刷新。看着分数随着 evaluator 消化这批数据陆续落下来——全大写和不认同的边界用例和你手打的那几轮一样浮上来，只是规模大了。这就是你的监控面对真实流量时的样子，也正是下一章要挖的那堆被标记的 trace。

**小结**

好的监控是把你信噪分开的东西。生产意味着大量 trace，最重要的问题是**我该看哪些？**——监控就是回答这个的。

信号检测类监控到位之后，随时间推进的下一步是**平均指标追踪**——挑质量指标，盯着它们漂移。选指标的正确方式是**错误分析**：抽样看你现在能抓到的那些出乎意料的 trace，按失败模式归类，再把失败模式变成 evaluator。[Academy 的 monitoring 课](https://langfuse.com/academy/monitoring)讲得更深。

这些监控抓到的 trace 也是下一步 `05-dataset` 最好的素材来源，因为它们是「你想锁住或修掉的行为」的真实样本。

### 05 · Dataset（`checkpoint/05-dataset`）

**起点**

```bash
git checkout checkpoint/05-dataset
```

你有一个已埋点、带用户/会话属性、且已配监控的应用。`data/seed-dataset.json` 和 `scripts/seed-dataset.ts` 在这个 checkpoint 里已经有了。

确认 `.env` 有：

```bash
DATASET_NAME=dad-it-support-workshop
```

**为什么要建数据集**

数据集是你对「系统在生产里会遇到什么」的表述——你预期的输入，以及每一条对应的好答案长什么样。把这套预期写下来，你就能在每次改动后拿 agent 重跑一遍，知道自己是改好了还是改坏了。一个好的数据集是「敢发布」和「迭代不回归」的地基。

详见 [Academy 的 datasets 课](https://langfuse.com/academy/datasets)。

**目标**

灌出第一份数据集，覆盖我们预期 Specs 要处理的请求类型。分两步：

1. **看懂 item 的形状** —— 每条 dataset item 都是同样三个字段，我们要让它和 agent 的真实输入对上。
2. **把数据集灌到 Langfuse**，好在下一步直接跑 experiment。

#### Step 1 —— 看懂 item 的形状

Langfuse 的 dataset item 形状固定——三个字段，一个必填、两个可选：

| 字段 | 必填 | 用途 |
| --- | --- | --- |
| `input` | 是 | 你喂给 agent 的东西。对我们来说就是 `/api/chat` 接受的 `{ messages: [...] }` 形状。 |
| `expectedOutput` | 否 | 好答案长什么样。自由格式——evaluator 用它比对实际输出与期望。 |
| `metadata` | 否 | 标签或其他字段，用于筛选和分组（`category`、`difficulty` 等）。 |

我们某一条 item 的概念形态是：

```json
{
  "input": "How do I turn Bluetooth on on my iPhone?",
  "expectedOutput": {
    "idealAnswer": "Open Settings, tap Bluetooth, and turn the Bluetooth switch on.",
    "expectedKeywords": ["Settings", "Bluetooth", "switch", "on"]
  },
  "metadata": { "category": "iphone-bluetooth", "difficulty": "easy" }
}
```

`expectedOutput` 里这两个字段回答的是两个不同的 evaluator 问题：

- **`idealAnswer`** 是给人读的参考回复。第 06 章那个 LLM-as-a-judge 的 `correctness` 回调读它来判断语义是否对得上。
- **`expectedKeywords`** 是一小组字符串，答案**必须**包含它们才算「覆盖了步骤」。第 06 章里实验脚本用它做确定性的 `keyword_overlap` 回调——快、便宜、不用调模型。

`metadata` 让你之后并排比较 experiment run 时，能按 category 或 difficulty 切片。

如果你去看 `data/seed-dataset.json` 里的实际 JSON，`input` 是 `/api/chat` 接受的完整 `{ messages: [...] }` 形状，外加一个 dataset 行的 `id` 字段。上面的例子被我们简化过，只是为了说明 **item 是什么**；磁盘上的格式才是实验脚本（第 06 章）能直接喂给 `runSupportConversation(...)`、不用重写输入的那个。

#### Step 2 —— 灌数据集

往 Langfuse dataset 里加条目有几种方式：

- **在 UI 里手动加**（Datasets → New item）。
- **通过 UI 上传 CSV / JSON** 文件。
- **从 Trace 视图把生产 trace 直接变成 dataset item** —— 一旦你的监控抓到了有意思的 trace，这是最强的一条路。
- **用 SDK / CLI 程序化灌入** —— 最适合像我们这样先来一次批量初始化。

本 workshop 走程序化这条路，因为我们已经有一份整理好的 JSON：

```bash
npm run dataset:seed
```

打开 Langfuse → **Datasets**。列表里应该出现新的 `dad-it-support-workshop`，14 条 item、0 次 experiment run（目前为止）：

![Langfuse 的 Datasets 列表——dad-it-support-workshop，14 条 item，还没有 run](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/datasets/05-dataset-list.png)

点进这个数据集，切到 **Items** 页签。应该能看到每条 item 的 input、expected output 和 metadata 列：

![dad-it-support-workshop 的 Items 视图——14 行，含 messages 输入、ideal answer + expected keywords、category/difficulty 元数据](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/datasets/05-dataset-items.png)

**起步数据集覆盖什么**

- iPhone 蓝牙基础与边界情况
- iPhone Wi-Fi 重连 + 「看不到网络」
- 拍照 + 分享到 WhatsApp
- Apple 地图导航 + 实时位置的功能限制
- 信息（Messages）基础
- 范围外（帮我报税、订火车票）
- 能力限制类（密码、实时位置）

以后要加条目，优先选**你在监控里真见过的信号**，而不是凭空编。

**怎么验证你做到了**

- 数据集和全部条目出现在 Langfuse。
- 条目的 input 长得像真实聊天轮次会有的 `messages` 数组。
- 你能说清这份数据集覆盖了哪些失败模式。

**小结**

数据集是你把「系统被期望处理什么」写下来的地方。一个好的数据集让你敢发布、也敢迭代而不回归。你可以用 [Langfuse CLI](https://langfuse.com/docs/api-and-data-platform/features/cli) 或 skill 灌数据集，可以在 UI 里从生产 trace 建，也可以像我们这样在代码里维护——哪种合适，取决于你最好的样本从哪来。

接下来我们用这份数据集对 agent 跑实验。

### 06 · Experiments（`checkpoint/06-experiments`）

**起点**

```bash
git checkout checkpoint/06-experiments
```

你的数据集已经灌进 Langfuse。`scripts/run-dataset.ts` 也已经在仓库里。

**为什么要做 experiment**

一条 trace 告诉你**一轮**的情况；一次 experiment 告诉你**整个数据集上**的行为。每次 experiment run 都做同样的三件事：

1. **从数据集里取出每一条 item。**
2. **把 item 的 input 喂给 agent** —— 用的是 web 应用同一份 `runSupportConversation(...)`，所以 trace 形状和生产完全一致。
3. **用一个或多个 evaluator 把实际输出和期望输出对比打分。**

不同 evaluator 回答不同的问题。想看 evaluator 类型全景和怎么选，见 [Academy 的 evaluate 课](https://langfuse.com/academy/evaluate)。本 workshop 用两个，先快速看一眼答案质量：

- **`keyword_overlap`**（确定性）—— *答案覆盖了我们预期的步骤吗？* 快、便宜，直接在实验脚本里算。
- **`correctness`**（LLM-as-a-judge）—— *答案保住了 ideal answer 的实质含义吗？* 语义等价检查：换个说法能过，漏掉必需细节或与事实矛盾就不能过。

两个分数都是 `runExperiment` 里的**回调 evaluator**。它们在每条 item 跑完后立刻在你的进程里执行，所以脚本退出时控制台摘要和 Langfuse 里的 run 都已经带上两个分数。本章刻意不用 Langfuse Platform evaluator：配一个需要已有 experiment 数据来预览和映射变量，在第一次 run 之前这是个先有鸡还是先有蛋的问题。

**目标**

本章结束时：

1. 你能按需把整个数据集对 agent 跑一遍。
2. 每条 item 都拿到 **`keyword_overlap`**（确定性）和 **`correctness`**（LLM-as-a-judge）两个分数，都来自 `runExperiment` 回调。
3. 两个分数加上逐条 trace 在 Langfuse 里可见，可以和以后的 run 对比。

#### Step 1 —— 读懂运行脚本

打开 `scripts/run-dataset.ts`。文件里带编号注释（`// --- 1. Boot the OpenTelemetry SDK ...`、`// --- 3. The deterministic evaluator ...` 等），可以一段段读。大体上它：

- 按 `DATASET_NAME` 从 Langfuse 拉取托管的数据集。
- 对每条 item，调用 web 应用同一份 `runSupportConversation(...)`。
- 用 `dataset.runExperiment(...)` 把逐条 trace 汇总成一行 run。
- 在同一次调用上挂 `keyword_overlap` 和 `correctness` 作为回调 evaluator。

它产出的 trace 和生产 trace 形状一样——同一个 `dad-it-support-chat-turn` 根、同样的 OpenAI generation、同样的工具 span。两个分数都不需要额外的 Langfuse UI 配置。

**`dataset.runExperiment(...)` 的组成部分**

整次 run 就是一次 `runExperiment` 调用，形状大致是：

```ts
await dataset.runExperiment({
  name: "Dad IT Support Agent experiment",
  runName,           // 这次 run 的唯一标签，会出现在 Runs 页签
  description: "...",
  metadata: { model: env.openaiModel },
  maxConcurrency: 1, // 一次跑一条

  task: async (item) => {
    const response = await runSupportConversation({ /* item.input */ });
    return response.answer;
  },

  evaluators: [
    async ({ output, expectedOutput }) => ({
      name: "keyword_overlap",
      value: keywordOverlap(output as string, (expectedOutput as any).expectedKeywords),
      comment: "..."
    }),
    async ({ output, expectedOutput }) => ({
      name: "correctness",
      value: /* 0 或 1，来自 LLM judge */,
      comment: "..."
    })
  ]
});
```

三点要理解：

- **`task`** 就是**你的应用逻辑**——我们直接调 `runSupportConversation(...)`，所以这个脚本产出的每条 trace 都和生产 trace 一模一样。
- **`evaluators`** 是一组回调。每个 evaluator 在 `task` 返回后运行，给该条 item 的 trace 挂一个分数。这里我们用一个确定性检查和一个 LLM-as-a-judge 检查。
- **`runName`** 把逐条 trace 归到 Langfuse Runs 视图里的一行。取一个每次都变的名字（我们带上了时间戳），免得两次 run 撞在一起。

#### Step 2 —— 看确定性的 `keyword_overlap` evaluator

`scripts/run-dataset.ts` 里那个 helper 在模型答案里找 dataset item 的 `expectedKeywords`，返回命中的比例。

为什么把它留在脚本里？

- 和实验代码其余部分放一起，好读。
- 和 app 共用同一套版本控制与评审流程。
- 它是确定性的，没有理由为它花一次 LLM 调用。

要记住 `keyword_overlap` 查的是**字面措辞**，不是行为。范围外那几条 item 期望出现 "outside"、"scope" 这类词，所以一句措辞不同但完全合理的拒绝可能在这几条上得 0 分。看到这些 item 的 `keyword_overlap` 低，应当把它当成「去读一遍答案、再和 `correctness` 对照」的提示，而不是自动判定失败——**两个指标打架，正是同时跑两个的意义之一。**

#### Step 3 —— 看 `correctness` 这个 LLM-as-a-judge 回调

`evaluators` 里第二个回调会用一段**语义等价**的 judge 提示词调 OpenAI。它把 `idealAnswer` 当作真源，问 agent 的答案是否保住了每一处实质含义、事实和约束——换个说法可以，漏掉必需细节或与事实矛盾不行。回调把 judge 的 true/false 映射成 `correctness` 的 `0` 或 `1`，外加一句简短理由。

为什么把 judge 做成回调，而不是 Langfuse Platform evaluator？

- 你能给**第一次** experiment run 打分，不用等 Evaluators UI 里有预览数据。
- judge 的提示词和模型和实验运行器一起住在 git 里。
- run 一结束，脚本打印的摘要里就有这两个分数。

judge 用的是 `.env` 里现有的 `OPENAI_API_KEY` / `OPENAI_MODEL`——agent 本来就在用的同一套凭据。本章**不需要**第 4 课配的 Langfuse 侧默认评估模型。

#### Step 4 —— 跑数据集

```bash
npm run dataset:run
```

脚本最后会在控制台打印一份格式化的 run 摘要。逐条 trace 和两个分数在 run 执行过程中就出现在 Langfuse 里。因为 evaluator 是回调，控制台摘要里**当场**就能看到 `keyword_overlap` 和 `correctness`，不是事后异步补上的。

**在 Langfuse 里看什么**

- 数据集下面新的 **Run** → 每条 item 一行，带**两个**分数（`keyword_overlap`、`correctness`）和一个 trace 链接。
- **逐条 trace** —— 形状和生产 trace 完全一致。
- 数据集的 **chart 视图** → 每个 run 上两个分数的平均值，方便以后改动后并排比较。

![Experiment 结果](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/experiments/experiment-results.png)

**怎么验证你做到了**

- 数据集下出现一行 run。
- 每条 item 都带上一条 trace 和两个分数。
- 控制台摘要同时打印了 `keyword_overlap` 和 `correctness`。
- trace 形状和正常的生产 trace 一致。

**小结**

两种打分方式给了你同一次 run 的两个视角：**关键词命中**回答「我们覆盖了对的步骤吗」，**correctness** 回答「答案真的对吗」。两者都作为 `runExperiment` 的回调运行，所以第一次 workshop run 不用配任何 platform evaluator 就是全打分的。

[**Langfuse skill**](https://github.com/langfuse/skills)（`/langfuse`）知道推荐的 evaluator 形状和配置模式——这份 walkthrough 存在的意义是让你看到 skill 底下在做什么。experiments 的更多内容见 [Academy 的课](https://langfuse.com/academy/experiments)。

### 07 · Evaluation（`checkpoint/07-evaluation`）

**起点**

```bash
git checkout checkpoint/07-evaluation
```

你的应用已埋点、已配监控、有托管数据集，并且至少跑过一次 experiment、拿到 `keyword_overlap` 和 `correctness` 两个分数。现在你对应用做一处改动，重跑 experiment，看它是帮忙还是帮倒忙。

动手改之前，先看你第一次 experiment run。打开数据集 → **Runs** 页签，看平均值：

- `correctness` 平均 —— judge 判定「真的对」的比例是多少？
- `keyword_overlap` 平均 —— 覆盖了预期步骤的比例是多少？

把任一分偏低的 item 打开读 agent 的答案。这个阶段常见的情况是：agent 漏了一步、拒绝了本来该答的、或者给的是泛泛建议而不是针对 iPhone 的具体步骤。你看到的**就是接下来要试着修的那个问题**。

**为什么要用 experiment 评估改动**

只要你动了 AI 应用里的任何东西——提示词、模型、传进去的上下文，甚至 agent 架构——你都想知道这个改动到底有没有让系统变好。肉眼看一两条输出感觉不错，但不具备推广性。拿同一份数据集对新版本重跑一遍、把分数和旧 run 比，是最接近「测量」的做法。

这也是让你闭合回路、**带着信心发布**的东西：新 run 的平均分上去了（而且你读了足够多的逐条用例，确认分数反映的是真实情况），你就有了部署这次改动的证据。

**你可以改什么**

本章围绕 prompt 迭代展开，因为改 prompt 摩擦最小。换别的东西时流程完全一样：

- **模型** —— 试个更强或更便宜的，重跑。
- **上下文** —— 在 system prompt 或工具结果里增删字段。
- **agent 架构** —— 加工具、改工具顺序、改重试。
- **提示词** —— 本章要做的。

形状永远一样：改**一处**（或一组配置），重跑数据集，并排比较。

**目标**

改动 prompt 里的某处，让 experiment 结果变好——以数据集整体 `correctness` 和 `keyword_overlap` 上升来衡量。

三个环节：

1. **改一处** —— 换 prompt 变体，或直接在 Langfuse UI 里编辑。
2. **对新的 prompt 重跑数据集。**
3. **并排比较两次 run**，决定要不要发布。

#### Step 1 —— 改 prompt

改动应当由你在第 1 次 run 里看到的东西驱动——比如某些 item `correctness` 低，是因为 agent 面对范围外问题时绕着说，而没有干脆拒绝。针对这一点，一个具体的改法：

> 加一条规则：*「如果请求超出 iPhone 帮助范围（报税、订票、任何需要访问实时账户的事），用一句话直接说明——你帮不了什么、能帮什么——然后停下。不要尝试回答这个请求。」*

这让范围外行为变成显式规则，而不是让模型即兴发挥。

两种改法：

**方案 A —— 在 Langfuse 侧改（在 UI 里新建版本）：**

Prompts → `dad-it-support-agent` → 新建版本或草稿 → 把上面那条规则加到 **Rules** 段 → 保存这个版本 → 把新版本提升到 `production` 标签。解析器是按标签取 prompt 的，所以下一次请求会自动用上新版本。这也是你团队在生产里做持续迭代会用的流程。

![在 Langfuse 里复核 prompt 改动——v1 与草稿的并排 diff，新增的范围外规则高亮显示](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/evaluate-a-change/07-evaluate-a-change-prompt-diff.png)

**方案 B —— 在代码侧改（编辑 `src/server/support-agent.ts` 再重新发布）：**

打开 `src/server/support-agent.ts`，把同一条规则加到 `SYSTEM_PROMPT` 常量的 Rules 块里，然后发布：

```bash
npm run prompt:publish
```

仓库还自带一个 `gentler` 变体可以直接切过去（`WORKSHOP_PROMPT_VARIANT=gentler npm run prompt:publish`）——如果你只想看到**随便一处** prompt 改动，而不是自己设计，这个很省事。

两条路最后都得到一个新的 prompt 版本，下一次 `runSupportConversation(...)` 调用就会用它。

#### Step 2 —— 重跑数据集

```bash
npm run dataset:run
```

现在同一个数据集下有了两次 run，各自关联到不同的 prompt 版本。第 06 章那两个 `keyword_overlap` 和 `correctness` 回调 evaluator 会在 `runExperiment` 里自动给新 run 打分。

#### Step 3 —— 对比

在 Langfuse 里：

- 数据集 → **Runs** 页签 → 两行都可见，带 `keyword_overlap` 和 `correctness` 平均值。
- **Chart 视图** → 每次 run 的平均值并排显示。
- 在侧栏把新的 run 加为 'Compare with'。

![并排对比](https://raw.githubusercontent.com/langfuse/langfuse-workshop/main/docs/images/evaluate-a-change/side-by-side-runs.png)

要关注的：

- 哪些 item 变好了（预期内的）。
- 哪些 item 退步了（这部分才是评估显得有用的地方）。
- prompt 改动是否改变了行为分布（拒绝变多了？回答更笃定了？每次回复步骤变多了？）。

**怎么验证你做到了**

- 数据集下出现**两次** run，分别关联到不同的 prompt 版本。
- 两个分数（`keyword_overlap`、`correctness`）都有可对比的平均值。
- `npm run dataset:run` 的控制台摘要里已经列出了新 run 的两个分数。

**小结**

闭合回路——改 → 重跑 → 对比 → 决定——是让 prompt 或模型改动从「凭感觉」变成工程决策的东西。以后每次改动都有一个免费的基线可以量。

[**Langfuse skill**](https://github.com/langfuse/skills)（`/langfuse`）会自动提升 prompt 版本、把 run 关联到版本、并生成对比图——这份 walkthrough 存在的意义是让你看到 skill 底下在做什么。

### 08 · Wrap-up（`checkpoint/08-wrap-up`）

**起点**

```bash
git checkout checkpoint/08-wrap-up
```

你已经把闭环的每一步都走完了。

**你现在应该能做到**

- 端到端 trace 一个 LLM 应用，并把结果当作调试界面来读。
- 把 prompt 和 trace 连起来，让 prompt 改动对下一条 trace 有可度量的影响。
- 自动发现有意思的生产行为（范围外、用户不认同）。
- 把产品边界变成一份由真实样例组成的起步数据集。
- 用同一份 agent 代码跑实验，不需要另写一套实现。
- 改动后对比两次 run，按分数**并且**通过读逐条输出，判断哪个配置更好。

**更大的图景**

本 workshop 里的 Langfuse 是一块**共享界面**，不只是可观测性：

- 理解行为 —— 每次交互都可检查
- 收集有代表性的样本 —— 生产流量喂出数据集
- 对比改动 —— 每次 prompt 或代码改动都有基线
- 持续改进系统 —— 闭环回到自己身上

**几个收尾问题**

- tracing 揭示了哪些原先看不见的东西？
- 在你自己的应用里，你会最先监控哪些生产事件？
- 起步数据集你接下来要加什么？
- 第一次 prompt 迭代之后，你要测的下一处改动是什么？
- 在你真实的应用里，哪一步用 `/langfuse` skill 能省掉最多手搓？

**回到自己的应用怎么做**

按这个顺序来：

1. **先把 [Langfuse CLI](https://langfuse.com/docs/api-and-data-platform/features/cli) 跑起来** —— 这样你能从终端管理 prompt、dataset 和 run。CLI 和 SDK 共用同一套项目 API key，没有单独的 CLI 登录步骤。把这三个值留在你应用的本地 `.env` 里：

   ```dotenv
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

   然后从加载了该文件的 shell 里跑 CLI：

   ```bash
   npx @langfuse/cli api __schema
   ```

   想用全局命令就装发布的包：

   ```bash
   npm install -g @langfuse/cli
   langfuse api __schema
   ```

2. **装 [Langfuse skill](https://github.com/langfuse/skills)**（`/langfuse`）—— 它把这套课推荐的 tracing、prompt management、monitoring、evaluator 模式打包好了，直接套到你的代码库，不用一件件手搓：

   ```bash
   npx skills add langfuse/skills --skill "langfuse"
   ```

3. **挑你最小的一个用到 LLM 的场景**，先接 `observe(...)` + `observeOpenAI(...)`。**先拿到一条 trace，再谈别的。**
4. **等有了至少两个用户或两个会话的流量，再加用户 / 会话标识** —— 在那之前没有意义。
5. **第一份数据集要从真实 trace、和专家的讨论、或历史样例来**，而不是凭空想。数据集该覆盖什么，生产行为会随时间告诉你。
6. **跑一次实验，改一处，再跑一次**，然后重复。

每一步更宏观的材料，[Langfuse Academy](https://langfuse.com/academy) 都有专门的课：

- [The AI Engineering Loop](https://langfuse.com/academy/ai-engineering-loop)
- [Tracing](https://langfuse.com/academy/tracing)
- [Monitoring](https://langfuse.com/academy/monitoring)
- [Datasets](https://langfuse.com/academy/datasets)
- [Experiments](https://langfuse.com/academy/experiments)
- [Evaluate](https://langfuse.com/academy/evaluate)
