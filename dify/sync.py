#!/usr/bin/env python3
"""从内网 Dify 下载工作流 YAML 到本地 ./yaml/ 目录。

用法:
    python dify/sync.py --email <邮箱> --password <密码>
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DIFY_BASE = "http://agent.smart-zone-dev.gf.com.cn"

WORKFLOWS: list[tuple[str, str]] = [
    # 治理（app/prompts/_manifest.yaml 的 dify.file）读取的是这一份；旧文件名「主干工作流.yml」
    # 为 2026-08 冻结的拓扑参照，不再更新（ADR 0022 D1）
    ("d6c0ea8b-c037-4d63-95b4-cb3f02940d23", "场外交易-test"),
    ("07c56e04-2250-4f78-be36-768091d9939b", "标的智能化推断和分词工具"),
    ("d6a4f5e1-4ff0-4ac4-82c8-7bc63e327cc0", "标的相关性排序工具"),
    ("1f6dcea0-8765-4be0-b0af-1ba5cba54aa7", "场外交易-期权工具"),
    ("d8f57e9c-1a66-4c58-9eaa-a29573b7201a", "场外交易-互换工具"),
]

OUTPUT_DIR = Path(__file__).resolve().parent / "yaml"

# ---- 内部 helpers ----

def _make_opener() -> urllib.request.OpenerDirector:
    """创建带 Cookie 支持的 opener。"""
    cj = http.cookiejar.CookieJar()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    https_handler = urllib.request.HTTPSHandler(context=ctx)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), https_handler)


def _get_csrf(opener: urllib.request.OpenerDirector) -> str | None:
    """从 cookie jar 中取 csrf_token。"""
    for c in opener.handlers:
        if isinstance(c, urllib.request.HTTPCookieProcessor):
            for cookie in c.cookiejar:
                if cookie.name == "csrf_token":
                    return cookie.value
    return None


def _request(
    opener: urllib.request.OpenerDirector,
    method: str,
    path: str,
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    """发送 HTTP 请求，返回 response body。"""
    url = f"{DIFY_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    headers: dict[str, str] = {
        "Accept": "application/json, text/yaml, */*",
    }
    if data:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    resp = opener.open(req, timeout=120)
    return resp.read()


# ---- 业务流程 ----

def login(opener: urllib.request.OpenerDirector, email: str, password: str) -> str | None:
    """登录 Dify，返回 csrf_token。"""
    print(f"登录 Dify: {email}")
    raw = _request(opener, "POST", "/console/api/login", {"email": email, "password": password})
    data = json.loads(raw)
    if data.get("result") != "success":
        print(f"  [FAIL] 登录失败: {raw[:300].decode()}", file=sys.stderr)
        sys.exit(1)
    csrf = _get_csrf(opener)
    if not csrf:
        print("  [FAIL] 未获取到 csrf_token", file=sys.stderr)
        sys.exit(1)
    print("  [OK] 登录成功")
    return csrf


def download_one(opener: urllib.request.OpenerDirector, csrf: str, app_id: str, name: str) -> None:
    """下载单个工作流 YAML。"""
    print(f"下载: {name} ({app_id})")
    raw = _request(
        opener, "GET", f"/console/api/apps/{app_id}/export",
        extra_headers={"X-CSRF-Token": csrf},
    )
    data = json.loads(raw)
    yaml_text = data.get("data", "")
    if not yaml_text:
        print(f"  [FAIL] 响应中无 data 字段: {raw[:300].decode()}", file=sys.stderr)
        return
    filepath = OUTPUT_DIR / f"{name}.yml"
    filepath.write_text(yaml_text, encoding="utf-8")
    print(f"  [OK] {filepath}  ({len(yaml_text)} bytes)")


def git_push(target_branch: str = "feature-yaml") -> bool:
    """将 dify/yaml/ 目录的变更提交并推送到目标分支。返回是否有推送。"""
    repo_dir = Path(__file__).resolve().parent.parent  # 仓库根目录
    yaml_dir = OUTPUT_DIR.relative_to(repo_dir)

    # 切到目标分支（不存在则创建）
    r = _git(["checkout", target_branch], repo_dir)
    if r.returncode != 0:
        _git(["checkout", "--orphan", target_branch], repo_dir)
        _git(["rm", "-rf", "."], repo_dir)

    # 拉取最新（允许失败，分支可能还没推送过）
    _git(["pull", "origin", target_branch], repo_dir)

    _git(["add", str(yaml_dir)], repo_dir)

    r = _git(["diff", "--staged", "--quiet"], repo_dir)
    if r.returncode == 0:
        print("无变更，跳过推送")
        return False

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    _git(["commit", "-m", f"chore: 同步 Dify 工作流 YAML ({now})"], repo_dir)
    _git(["push", "origin", target_branch], repo_dir)
    print(f"已推送到 origin/{target_branch}")
    return True


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """执行 git 命令，允许失败（返回结果不抛异常）。"""
    cmd = ["git"] + args
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0 and r.stderr:
        print(f"  [git] {r.stderr.strip()}")
    return r


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 Dify 工作流 YAML")
    parser.add_argument(
        "--email",
        default=os.environ.get("DIFY_EMAIL"),
        help="Dify 登录邮箱",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("DIFY_PASSWORD"),
        help="Dify 登录密码",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="下载后自动 commit 并 push 到 feature-yaml 分支",
    )
    parser.add_argument(
        "--target-branch",
        default="feature-yaml",
        help="推送目标分支（默认 feature-yaml）",
    )
    args = parser.parse_args()

    if not args.email or not args.password:
        print("[FAIL] 请提供 --email --password，或设置 DIFY_EMAIL / DIFY_PASSWORD", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    opener = _make_opener()
    csrf = login(opener, args.email, args.password)

    for app_id, name in WORKFLOWS:
        download_one(opener, csrf, app_id, name)

    print(f"\n完成，共 {len(WORKFLOWS)} 个文件 → {OUTPUT_DIR}")

    if args.push:
        print()
        git_push(args.target_branch)


if __name__ == "__main__":
    main()
