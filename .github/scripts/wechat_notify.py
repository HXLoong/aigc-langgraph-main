#!/usr/bin/env python3
"""企微群机器人通知 GitHub PR / Issue 事件。

由 .github/workflows/wechat-notify.yml 调用。约定的环境变量：

  - WECHAT_WEBHOOK_URL  企微机器人 webhook URL（从 GitHub Secrets 注入）
  - GITHUB_EVENT_NAME   GitHub Actions 自动设置（pull_request / issues / ...）
  - GITHUB_EVENT_PATH   GitHub Actions 自动设置，指向当前 event payload JSON

退出码：
  0  发送成功 / 主动跳过（不支持的事件、过滤掉的 action、缺 secret）
  1  调用 webhook 失败或企微返回 errcode != 0
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Callable


def _truncate(text: str | None, limit: int = 200) -> str:
    if not text:
        return ""
    text = text.strip().replace("\r\n", "\n")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _color(state: str) -> str:
    return {
        "opened": "warning",
        "reopened": "warning",
        "ready_for_review": "warning",
        "closed": "comment",
        "merged": "info",
        "approved": "info",
        "changes_requested": "warning",
    }.get(state, "comment")


def build_pr_message(event: dict[str, Any]) -> str | None:
    action = event["action"]
    pr = event["pull_request"]
    title = pr["title"]
    number = pr["number"]
    url = pr["html_url"]
    user = pr["user"]["login"]
    base = pr["base"]["ref"]
    head = pr["head"]["ref"]

    if action == "closed":
        state = "merged" if pr.get("merged") else "closed"
        label = "PR 已合并" if pr.get("merged") else "PR 已关闭"
    elif action == "opened":
        state = "opened"
        label = "新 PR"
    elif action == "reopened":
        state = "reopened"
        label = "PR 重开"
    elif action == "ready_for_review":
        state = "ready_for_review"
        label = "PR 转正"
    else:
        return None

    return (
        f"**[{label}] #{number}** <font color=\"{_color(state)}\">{state}</font>\n"
        f"[{title}]({url})\n"
        f"作者：`{user}`\n"
        f"分支：`{head}` → `{base}`"
    )


def build_issue_message(event: dict[str, Any]) -> str | None:
    action = event["action"]
    issue = event["issue"]
    # issues 事件不会带 pull_request 字段；这里保险起见再判一次
    if "pull_request" in issue:
        return None

    title = issue["title"]
    number = issue["number"]
    url = issue["html_url"]
    user = issue["user"]["login"]

    if action == "opened":
        state, label = "opened", "新 Issue"
    elif action == "closed":
        state, label = "closed", "Issue 已关闭"
    elif action == "reopened":
        state, label = "reopened", "Issue 重开"
    else:
        return None

    return (
        f"**[{label}] #{number}** <font color=\"{_color(state)}\">{state}</font>\n"
        f"[{title}]({url})\n"
        f"作者：`{user}`"
    )


def build_review_message(event: dict[str, Any]) -> str | None:
    if event["action"] != "submitted":
        return None
    review = event["review"]
    state = review["state"]  # approved / changes_requested / commented
    # 普通 inline 注释（state=commented）走 pull_request_review_comment 事件更合适，
    # 这里跳过避免重复
    if state == "commented":
        return None

    pr = event["pull_request"]
    title = pr["title"]
    number = pr["number"]
    url = review.get("html_url") or pr["html_url"]
    user = review["user"]["login"]
    body = _truncate(review.get("body"))

    text = (
        f"**[PR Review] #{number}** <font color=\"{_color(state)}\">{state}</font>\n"
        f"[{title}]({url})\n"
        f"评审人：`{user}`"
    )
    if body:
        text += f"\n> {body}"
    return text


def build_comment_message(event: dict[str, Any]) -> str | None:
    if event["action"] != "created":
        return None
    issue = event["issue"]
    comment = event["comment"]
    body = _truncate(comment.get("body"))
    if not body:
        return None

    label = "PR 评论" if "pull_request" in issue else "Issue 评论"
    title = issue["title"]
    number = issue["number"]
    url = comment["html_url"]
    user = comment["user"]["login"]

    return (
        f"**[{label}] #{number}**\n"
        f"[{title}]({url})\n"
        f"评论者：`{user}`\n"
        f"> {body}"
    )


BUILDERS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "pull_request": build_pr_message,
    "issues": build_issue_message,
    "pull_request_review": build_review_message,
    "issue_comment": build_comment_message,
}


def _post(webhook: str, payload: dict[str, Any]) -> int:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            print(f"HTTP {resp.status} {raw}")
            if resp.status >= 400:
                return 1
            result = json.loads(raw)
            if result.get("errcode") != 0:
                print(f"wechat errcode != 0: {result}", file=sys.stderr)
                return 1
    except urllib.error.URLError as exc:
        print(f"webhook request failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    webhook = os.environ.get("WECHAT_WEBHOOK_URL", "").strip()
    if not webhook:
        # 缺 secret 时静默跳过（fork PR 拿不到 secret 是常态，不应当失败）
        print("WECHAT_WEBHOOK_URL not set, skip", file=sys.stderr)
        return 0

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_name or not event_path:
        print("missing GITHUB_EVENT_NAME or GITHUB_EVENT_PATH", file=sys.stderr)
        return 0

    with open(event_path, "r", encoding="utf-8") as f:
        event = json.load(f)

    builder = BUILDERS.get(event_name)
    if builder is None:
        print(f"unsupported event: {event_name}", file=sys.stderr)
        return 0

    content = builder(event)
    if content is None:
        print(f"skipped {event_name}.{event.get('action')}", file=sys.stderr)
        return 0

    repo = event.get("repository", {}).get("full_name", "")
    if repo:
        content = f"`{repo}`\n{content}"

    return _post(webhook, {"msgtype": "markdown", "markdown": {"content": content}})


if __name__ == "__main__":
    sys.exit(main())
