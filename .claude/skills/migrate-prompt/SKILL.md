---
name: migrate-prompt
description: 从一个 Dify YAML 文件迁移单个 LLM 节点的提示词到代码库。使用场景：业务方只改了 Dify 工作流中的某一个节点，需要把更新同步到 LangGraph 代码。
argument-hint: <dify-yaml-path> <node-title> [category]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# 迁移单个 Dify 提示词

## 参数
- `$1` = Dify YAML 文件路径
- `$2` = 要迁移的 LLM 节点标题（如"互换-节点-下单"）
- `$3` = 可选的目标分类（swap / option / option_close / ticker）

## 执行步骤

1. **加载上下文**
   - 读 `@.claude/rules/prompt-management.md`
   - 读 `@app/prompts/__init__.py` 理解 loader 格式

2. **从 YAML 提取指定节点的提示词**
   使用 `python -c` 脚本提取（避免启动完整 export 脚本）：
   ```bash
   python -c "
   import yaml
   with open('$1') as f:
       data = yaml.safe_load(f)
   nodes = data['workflow']['graph']['nodes']
   target = [n for n in nodes if n['data'].get('title') == '$2' and n['data'].get('type') == 'llm']
   if not target:
       print('NOT_FOUND'); exit(1)
   node = target[0]
   for p in node['data'].get('prompt_template', []):
       print(f'### [{p[\"role\"]}]')
       print(p['text'])
       print()
   "
   ```

3. **判断归类**
   - 标题含"互换" → `swap/`
   - 标题含"平仓" → `option_close/`
   - 标题含"标的" → `ticker/`
   - 其他期权 → `option/`
   - 若用户指定了 `$3`，用 `$3`

4. **生成 .md 文件**
   把提取的 system/user 按 loader 格式写到 `app/prompts/<category>/<snake_case>.md`
   格式参考：
   ```markdown
   # <原 Dify 节点标题>

   - **source**: Dify YAML (<yaml 文件名>)
   - **node_id**: `<id>`
   - **model**: `<model>`
   - **migrated_at**: <today>

   ## [system]
   ```
   <system prompt 原文>
   ```

   ## [user]
   ```
   <user template 原文>
   ```
   ```

5. **验证加载**
   ```bash
   python -c "from app.prompts import load_prompt; p = load_prompt('<category>', '<name>'); print(f'system={len(p.system)}ch user={len(p.user_template)}ch')"
   ```

6. **汇报**
   - 新增/覆盖了哪个文件
   - system / user 段的字符数
   - 下一步建议：在哪个节点函数用这个 prompt（grep 查看是否有现成的）

## 注意

- 若目标文件已存在，**不要静默覆盖**，先 `diff` 给用户看
- 不要改其他提示词文件
- 不要直接跑 pytest（留给用户手动确认）

## 错误处理

- YAML 解析失败 → 提示用户检查文件格式
- 节点标题找不到 → 列出所有 LLM 节点标题供用户选择
- 目标分类不合法 → 列出可用分类
