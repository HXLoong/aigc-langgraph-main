# 问题追踪器：GitHub

本仓库的 issue 和 PRD 存放在 GitHub Issues 中，所有操作通过 `gh` CLI 完成。

## 操作约定

- **创建 issue**：`gh issue create --title "..." --body "..."`，多行内容使用 heredoc。
- **查看 issue**：`gh issue view <number> --comments`，可配合 `jq` 过滤评论和标签。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，可加 `--label` 和 `--state` 过滤。
- **评论 issue**：`gh issue comment <number> --body "..."`
- **添加 / 移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭 issue**：`gh issue close <number> --comment "..."`

仓库信息从 `git remote -v` 推断——在克隆目录内运行 `gh` 时会自动识别。

## 当技能说"发布到问题追踪器"时

创建一个 GitHub issue。

## 当技能说"获取相关工单"时

运行 `gh issue view <number> --comments`。
