#!/usr/bin/env python3
"""启动本地 LangGraph 回归任务队列页面。

每个任务绑定一份或多份 JSONL 数据集和一份独立运行配置。服务使用单调度线程串行
执行任务；回归脚本逐用例输出结构化事件，因此页面能在整批结束前查看每条
用例的输入、输出、断言结果和 LangGraph 结构化输出。
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import logging
import mimetypes
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from langgraph_direct_regression import (
    DEFAULT_BOT_NAME,
    DEFAULT_DATASET_DIR,
    DEFAULT_GUID,
    DEFAULT_OPTION_COUNTERPARTIES,
    DEFAULT_SWAP_COUNTERPARTIES,
    RUNNER_EVENT_PREFIX,
    LangGraphClient,
    ensure_safe_target,
    load_cases,
    parse_dotenv_value,
    select_cases,
)
from langgraph_direct_regression import (
    RunnerError as RegressionRunnerError,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
HTML_PATH = SCRIPT_DIR / "automation_runner.html"
LANGGRAPH_SCRIPT = SCRIPT_DIR / "langgraph_direct_regression.py"
WECOM_SCRIPT = SCRIPT_DIR / "wecom_dataset_push.py"
DOTENV_PATH = REPO_ROOT / ".env"
LANGGRAPH_DOTENV_PATH = REPO_ROOT / ".env"
DATASET_ROOT = DEFAULT_DATASET_DIR
DEFAULT_LANGGRAPH_BASE = "http://127.0.0.1:8000"

MAX_REQUEST_BYTES = 128 * 1024
MAX_LOG_CHARS = 2 * 1024 * 1024
MAX_COUNTERPARTY_JSON_BYTES = 24 * 1024
MAX_COUNTERPARTIES = 200
MAX_DATASETS_PER_JOB = 100
MAX_JOBS = 100
MAX_TASK_NAME_CHARS = 100
MAX_CHAT_QUERY_CHARS = 32 * 1024
MAX_CHAT_QUOTE_CHARS = 128 * 1024
MAX_CONVERSATION_ID_CHARS = 256
ROOM_ID_RE = re.compile(r"^\d{10,32}$")
JOB_ID_RE = r"([0-9a-f]{32})"
REPORT_LINE_RE = re.compile(r"^(?:Markdown|JSON) report:\s*(.+)$")
TERMINAL_STATUSES = {"success", "failed", "cancelled"}
MOVABLE_STATUSES = {"ready", "queued"}
CommandSpec = tuple[str, list[str], dict[str, str]]
logger = logging.getLogger(__name__)


class RunnerServerError(ValueError):
    """页面参数、队列操作或本地执行异常。"""


@dataclass
class Job:
    job_id: str
    name: str
    dataset: str
    config: dict[str, Any]
    commands: list[CommandSpec]
    datasets: list[str] = field(default_factory=list)
    status: str = "ready"
    return_code: int | None = None
    log: str = ""
    reports: list[Path] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    case_details: dict[int, dict[str, Any]] = field(default_factory=dict, repr=False)
    total_cases: int = 0
    completed_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    current_case_index: int | None = None
    cancel_requested: bool = False
    process: subprocess.Popen[str] | None = field(default=None, repr=False)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None


def load_dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = parse_dotenv_value(value)
    return values


def load_runner_config_values(
    primary_path: Path = DOTENV_PATH,
    fallback_path: Path = LANGGRAPH_DOTENV_PATH,
) -> dict[str, str]:
    """读取 aigc-langgraph/.env 中的测试身份配置。"""
    values = load_dotenv_values(primary_path)
    fallback = load_dotenv_values(fallback_path)
    for name in ("EVAL_USER_ID", "EVAL_ROOM_ID"):
        if not values.get(name) and fallback.get(name):
            values[name] = fallback[name]
    return values


def first_config(values: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = (os.environ.get(name) or values.get(name) or "").strip()
        if value:
            return value
    return default


def discover_datasets() -> list[dict[str, Any]]:
    """按文件名排序返回分类目录直属 JSONL，不扫描历史归档。"""
    datasets: list[dict[str, Any]] = []
    if not DATASET_ROOT.is_dir():
        return datasets
    for path in sorted(DATASET_ROOT.glob("*.jsonl")):
        try:
            count = len(load_cases([path]))
        except (OSError, UnicodeError, RegressionRunnerError):
            continue
        relative = str(path.relative_to(REPO_ROOT))
        datasets.append({"path": relative, "name": path.name, "cases": count})
    return datasets


def build_public_config(values: dict[str, str]) -> dict[str, Any]:
    return {
        "base_url": first_config(
            values, "LANGGRAPH_BASE", default=DEFAULT_LANGGRAPH_BASE
        ),
        "user_id": first_config(values, "EVAL_USER_ID"),
        "room_id": first_config(values, "EVAL_ROOM_ID"),
        "option_counterparties": first_config(
            values,
            "LANGGRAPH_OPTION_COUNTERPARTIES",
            "DIFY_OPTION_COUNTERPARTIES",
            default=json.dumps(DEFAULT_OPTION_COUNTERPARTIES, ensure_ascii=False),
        ),
        "swap_counterparties": first_config(
            values,
            "LANGGRAPH_SWAP_COUNTERPARTIES",
            "DIFY_SWAP_COUNTERPARTIES",
            default=json.dumps(DEFAULT_SWAP_COUNTERPARTIES, ensure_ascii=False),
        ),
        "datasets": discover_datasets(),
        "pause_supported": (
            hasattr(os, "killpg")
            and hasattr(signal, "SIGSTOP")
            and hasattr(signal, "SIGCONT")
        ),
    }


def render_runner_html(runner_token: str, config: dict[str, Any]) -> str:
    content = HTML_PATH.read_text(encoding="utf-8")
    replacements = {
        "__RUNNER_TOKEN__": runner_token,
        "__DEFAULT_LANGGRAPH_BASE__": str(config["base_url"]),
        "__DEFAULT_USER_ID__": str(config["user_id"]),
        "__DEFAULT_ROOM_ID__": str(config["room_id"]),
    }
    for marker, value in replacements.items():
        content = content.replace(marker, html_lib.escape(value, quote=True))
    return content


def parse_int(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int | None:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RunnerServerError(f"{label}必须是整数") from exc
    if not minimum <= parsed <= maximum:
        raise RunnerServerError(f"{label}必须在 {minimum} 到 {maximum} 之间")
    return parsed


def parse_float(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: float,
    default: float,
) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RunnerServerError(f"{label}必须是数字") from exc
    if not minimum <= parsed <= maximum:
        raise RunnerServerError(f"{label}必须在 {minimum} 到 {maximum} 之间")
    return parsed


def split_values(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    return [part.strip() for part in re.split(r"[,，\n]", value) if part.strip()]


def parse_counterparties_json(value: Any, label: str) -> tuple[str, int]:
    if not isinstance(value, str) or not value.strip():
        raise RunnerServerError(f"请填写{label}")
    raw_value = value.strip()
    if len(raw_value.encode("utf-8")) > MAX_COUNTERPARTY_JSON_BYTES:
        raise RunnerServerError(f"{label}不能超过 {MAX_COUNTERPARTY_JSON_BYTES} 字节")
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RunnerServerError(
            f"{label}不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列"
        ) from exc
    if not isinstance(parsed, list):
        raise RunnerServerError(f"{label}必须是 JSON 数组")
    if len(parsed) > MAX_COUNTERPARTIES:
        raise RunnerServerError(f"{label}最多允许 {MAX_COUNTERPARTIES} 条")

    seen_ids: set[int] = set()
    seen_short_names: set[str] = set()
    for index, item in enumerate(parsed, 1):
        location = f"{label}第 {index} 条"
        if not isinstance(item, dict):
            raise RunnerServerError(f"{location}必须是 JSON 对象")
        ctpty_id = item.get("ctptyId")
        if isinstance(ctpty_id, bool) or not isinstance(ctpty_id, int) or ctpty_id <= 0:
            raise RunnerServerError(f"{location}的 ctptyId 必须是正整数")
        short_name = item.get("shortName")
        if not isinstance(short_name, str) or not short_name.strip():
            raise RunnerServerError(f"{location}的 shortName 不能为空")
        for field_name in ("longName", "sort"):
            if not isinstance(item.get(field_name), str):
                raise RunnerServerError(f"{location}的 {field_name} 必须是字符串")
        if ctpty_id in seen_ids:
            raise RunnerServerError(f"{label}存在重复 ctptyId：{ctpty_id}")
        if short_name in seen_short_names:
            raise RunnerServerError(f"{label}存在重复 shortName：{short_name}")
        seen_ids.add(ctpty_id)
        seen_short_names.add(short_name)
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), len(parsed)


def parse_chat_text(
    value: Any,
    label: str,
    *,
    maximum: int,
    required: bool = False,
    trim: bool = True,
) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip() if trim else value
    else:
        raise RunnerServerError(f"{label}必须是文本")
    if required and not text:
        raise RunnerServerError(f"请输入{label}")
    if "\x00" in text:
        raise RunnerServerError(f"{label}包含无效字符")
    if len(text) > maximum:
        raise RunnerServerError(f"{label}不能超过 {maximum} 个字符")
    return text


def build_chat_turn(
    payload: dict[str, Any],
    *,
    dotenv_values: dict[str, str] | None = None,
    client_factory: Any = LangGraphClient,
) -> tuple[Any, dict[str, Any]]:
    """校验自由对话参数并构造一次无服务端持久状态的 LangGraph 请求。"""
    values = load_runner_config_values() if dotenv_values is None else dotenv_values
    query = parse_chat_text(
        payload.get("query"), "测试指令", maximum=MAX_CHAT_QUERY_CHARS, required=True
    )
    quote_content = parse_chat_text(
        payload.get("quote_content"),
        "引用内容",
        maximum=MAX_CHAT_QUOTE_CHARS,
        trim=False,
    )
    conversation_id = parse_chat_text(
        payload.get("conversation_id"),
        "conversation_id",
        maximum=MAX_CONVERSATION_ID_CHARS,
    ) or f"ai-test-chat-{uuid.uuid4().hex}"
    for field_name, label, default in (
        ("at_bot", "@机器人选项", True),
        ("insecure", "HTTPS 校验选项", False),
    ):
        if not isinstance(payload.get(field_name, default), bool):
            raise RunnerServerError(f"{label}必须是布尔值")

    base_url = parse_chat_text(
        payload.get("base_url")
        or first_config(values, "LANGGRAPH_BASE", default=DEFAULT_LANGGRAPH_BASE),
        "LangGraph 地址",
        maximum=2048,
        required=True,
    ).rstrip("/")
    try:
        ensure_safe_target(base_url, False)
    except RegressionRunnerError as exc:
        raise RunnerServerError(str(exc)) from exc

    room_id = parse_chat_text(
        payload.get("room_id") or first_config(values, "EVAL_ROOM_ID"),
        "企微群 ID",
        maximum=32,
        required=True,
    )
    if not ROOM_ID_RE.fullmatch(room_id):
        raise RunnerServerError("企微群 ID 必须是 10-32 位数字")
    user_id = parse_chat_text(
        payload.get("user_id") or first_config(values, "EVAL_USER_ID"),
        "用户 ID",
        maximum=256,
        required=True,
    )
    option_json, _ = parse_counterparties_json(
        payload.get("option_counterparties")
        or first_config(
            values,
            "LANGGRAPH_OPTION_COUNTERPARTIES",
            "DIFY_OPTION_COUNTERPARTIES",
            default=json.dumps(DEFAULT_OPTION_COUNTERPARTIES, ensure_ascii=False),
        ),
        "期权交易对手候选",
    )
    swap_json, _ = parse_counterparties_json(
        payload.get("swap_counterparties")
        or first_config(
            values,
            "LANGGRAPH_SWAP_COUNTERPARTIES",
            "DIFY_SWAP_COUNTERPARTIES",
            default=json.dumps(DEFAULT_SWAP_COUNTERPARTIES, ensure_ascii=False),
        ),
        "互换交易对手候选",
    )
    client = client_factory(
        base_url=base_url,
        user_id=user_id,
        room_id=room_id,
        bot_name=first_config(
            values, "LANGGRAPH_BOT_NAME", "DIFY_BOT_NAME", default=DEFAULT_BOT_NAME
        ),
        guid=first_config(
            values, "LANGGRAPH_EVAL_GUID", "DIFY_EVAL_GUID", default=DEFAULT_GUID
        ),
        option_counterparties=option_json,
        swap_counterparties=swap_json,
        timeout=parse_float(
            payload.get("langgraph_timeout"),
            "LangGraph 超时",
            minimum=1,
            maximum=3600,
            default=300,
        ),
        retries=int(
            parse_int(
                payload.get("langgraph_retries"),
                "LangGraph 重试次数",
                minimum=0,
                maximum=10,
                default=2,
            )
            or 0
        ),
        throttle_ms=0,
        verify_tls=payload.get("insecure") is not True,
    )
    return client, {
        "query": query,
        "quote_content": quote_content,
        "conversation_id": conversation_id,
        "at_bot": payload.get("at_bot", True),
    }


def send_chat_turn(
    payload: dict[str, Any],
    *,
    dotenv_values: dict[str, str] | None = None,
    client_factory: Any = LangGraphClient,
) -> dict[str, Any]:
    try:
        client, turn = build_chat_turn(
            payload, dotenv_values=dotenv_values, client_factory=client_factory
        )
        answer, workflow_run_id, conversation_id, elapsed = client.send(**turn)
    except RegressionRunnerError as exc:
        raise RunnerServerError(str(exc)) from exc
    return {
        "answer": answer,
        "conversation_id": conversation_id,
        "workflow_run_id": workflow_run_id,
        "duration": elapsed,
        "outputs": dict(getattr(client, "last_outputs", {}) or {}),
    }


def resolve_dataset(value: Any) -> Path:
    """解析并校验一份仓库内 JSONL 数据集。"""
    if not isinstance(value, str) or not value.strip():
        raise RunnerServerError("请选择或填写一份测试用例集")
    raw_path = Path(value.strip()).expanduser()
    path = raw_path if raw_path.is_absolute() else REPO_ROOT / raw_path
    path = path.resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise RunnerServerError("测试用例集必须位于当前仓库内") from exc
    if path.suffix.lower() != ".jsonl" or not path.is_file():
        raise RunnerServerError("测试用例集必须是仓库内存在的 .jsonl 文件")
    return path


def payload_datasets(payload: dict[str, Any]) -> list[Path]:
    """读取新 ``datasets`` 数组，同时兼容旧版单个 ``dataset`` 参数。"""
    values = payload.get("datasets")
    if values is None:
        values = [payload.get("dataset")]
    elif not isinstance(values, list):
        raise RunnerServerError("测试用例集 datasets 必须是数组")
    if not values or all(value is None or value == "" for value in values):
        raise RunnerServerError("请至少选择或填写一份测试用例集")
    if len(values) > MAX_DATASETS_PER_JOB:
        raise RunnerServerError(f"每个任务最多选择 {MAX_DATASETS_PER_JOB} 份测试用例集")

    datasets: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        dataset = resolve_dataset(value)
        if dataset not in seen:
            seen.add(dataset)
            datasets.append(dataset)
    return datasets


def append_filters(command: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    limit = parse_int(payload.get("limit"), "执行数量", minimum=1, maximum=10000)
    if limit is not None:
        command.extend(["--limit", str(limit)])
        summary["limit"] = limit
    keyword = str(payload.get("keyword") or "").strip()
    if keyword:
        command.extend(["--keyword", keyword])
        summary["keyword"] = keyword
    names = split_values(payload.get("names"))
    case_nos = split_values(payload.get("case_nos"))
    for name in names:
        command.extend(["--name", name])
    for case_no in case_nos:
        command.extend(["--case-no", case_no])
    if names:
        summary["names"] = names
    if case_nos:
        summary["case_nos"] = case_nos
    return summary


def build_job(
    payload: dict[str, Any],
    *,
    job_id: str | None = None,
    allow_non_dev: bool = False,
) -> Job:
    """校验页面参数并构造多数据集、单配置任务。"""
    datasets = payload_datasets(payload)
    try:
        loaded_cases = load_cases(datasets)
    except (OSError, UnicodeError, RegressionRunnerError) as exc:
        raise RunnerServerError(f"测试用例集不可执行：{exc}") from exc
    dataset_args = [str(dataset.relative_to(REPO_ROOT)) for dataset in datasets]
    run_langgraph = payload.get("run_langgraph") is True
    push_wecom = payload.get("push_wecom") is True
    if not run_langgraph:
        raise RunnerServerError("任务必须运行 LangGraph 直接回归")
    if push_wecom and payload.get("shuffle") is True:
        raise RunnerServerError("推送企微时不能随机打乱用例")

    default_task_name = (
        datasets[0].stem
        if len(datasets) == 1
        else f"{datasets[0].stem} 等 {len(datasets)} 个数据集"
    )
    task_name = str(payload.get("task_name") or "").strip() or default_task_name
    if len(task_name) > MAX_TASK_NAME_CHARS or "\x00" in task_name:
        raise RunnerServerError(f"任务名称不能超过 {MAX_TASK_NAME_CHARS} 个字符")

    runner_script = WECOM_SCRIPT if push_wecom else LANGGRAPH_SCRIPT
    command = [
        sys.executable,
        "-u",
        str(runner_script),
    ]
    for dataset_arg in dataset_args:
        command.extend(["--data", dataset_arg])
    command.extend(["--task-name", task_name])
    command.append("--runner-events")
    if allow_non_dev:
        command.append("--allow-non-dev")
    filters = append_filters(command, payload)
    if payload.get("shuffle") is True:
        seed = parse_int(
            payload.get("seed"),
            "随机种子",
            minimum=0,
            maximum=2_147_483_647,
            default=20260810,
        )
        command.extend(["--shuffle", "--seed", str(seed)])
        filters.update({"shuffle": True, "seed": seed})
    try:
        selected_cases = select_cases(
            loaded_cases,
            names=filters.get("names", []),
            case_nos=filters.get("case_nos", []),
            keyword=str(filters.get("keyword") or ""),
            limit=filters.get("limit"),
            shuffle=filters.get("shuffle") is True,
            seed=int(filters.get("seed") or 20260810),
        )
    except RegressionRunnerError as exc:
        raise RunnerServerError(f"测试用例筛选条件无效：{exc}") from exc
    if not selected_cases:
        raise RunnerServerError("筛选后没有可执行用例")

    base_url = str(payload.get("base_url") or "").strip()
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RunnerServerError("LangGraph 地址格式不正确")
        command.extend(["--base-url", base_url])

    room_id = str(payload.get("room_id") or "").strip()
    if not ROOM_ID_RE.fullmatch(room_id):
        raise RunnerServerError("企微群 ID 必须是 10-32 位数字")
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id or len(user_id) > 256 or "\x00" in user_id:
        raise RunnerServerError("请输入有效的用户 ID")

    option_json, option_count = parse_counterparties_json(
        payload.get("option_counterparties"), "期权交易对手候选"
    )
    swap_json, swap_count = parse_counterparties_json(
        payload.get("swap_counterparties"), "互换交易对手候选"
    )
    bot_name = str(payload.get("bot_name") or "").strip()
    if bot_name:
        command.extend(["--bot-name", bot_name])
    command.extend(
        [
            "--timeout",
            str(
                parse_float(
                    payload.get("langgraph_timeout"),
                    "LangGraph 超时",
                    minimum=1,
                    maximum=3600,
                    default=300,
                )
            ),
            "--retries",
            str(
                parse_int(
                    payload.get("langgraph_retries"),
                    "LangGraph 重试次数",
                    minimum=0,
                    maximum=10,
                    default=2,
                )
            ),
            "--throttle-ms",
            str(
                parse_int(
                    payload.get("throttle_ms"),
                    "请求间隔",
                    minimum=0,
                    maximum=60000,
                    default=0,
                )
            ),
        ]
    )
    if payload.get("keep_expected_mentions") is True:
        command.append("--keep-expected-mentions")
    if payload.get("insecure") is True:
        command.append("--insecure")
    if push_wecom:
        command.extend(
            [
                "--wecom-timeout",
                str(
                    parse_float(
                        payload.get("wecom_timeout"),
                        "企微超时",
                        minimum=1,
                        maximum=300,
                        default=15,
                    )
                ),
                "--wecom-retries",
                str(
                    parse_int(
                        payload.get("wecom_retries"),
                        "企微报告上传重试次数",
                        minimum=0,
                        maximum=10,
                        default=2,
                    )
                ),
                "--send",
            ]
        )

    env_overrides = {
        "EVAL_USER_ID": user_id,
        "EVAL_ROOM_ID": room_id,
        "LANGGRAPH_OPTION_COUNTERPARTIES": option_json,
        "LANGGRAPH_SWAP_COUNTERPARTIES": swap_json,
    }

    config = {
        "mode": "LangGraph 回归 + 企微推送" if push_wecom else "LangGraph 直接回归",
        "base_url": base_url or "读取 .env",
        "user_id": user_id,
        "room_id": room_id,
        "option_counterparties": option_count,
        "swap_counterparties": swap_count,
        "filters": filters,
    }
    label = "LangGraph 回归 + 企微报告推送" if push_wecom else "LangGraph 直接回归"
    job = Job(
        job_id=job_id or uuid.uuid4().hex,
        name=task_name,
        dataset=dataset_args[0],
        datasets=dataset_args,
        config=config,
        commands=[(label, command, env_overrides)],
    )
    job.total_cases = len(selected_cases)
    job.cases = [
        {
            "index": index,
            "name": str(case.get("name") or f"用例 {index}"),
            "case_no": str(case.get("caseNo") or ""),
            "status": "pending",
            "duration": None,
            "failure": "",
        }
        for index, case in enumerate(selected_cases, 1)
    ]
    return job


def append_log(job: Job, content: str) -> None:
    job.log = (job.log + content)[-MAX_LOG_CHARS:]


def clear_job_secrets(job: Job) -> None:
    for _, _, env_overrides in job.commands:
        env_overrides.clear()


def case_failure_summary(result: dict[str, Any]) -> str:
    error = str(result.get("error") or "").strip()
    if error:
        return error
    for turn in result.get("turns") or []:
        assertion = turn.get("assertion") if isinstance(turn, dict) else None
        failures = assertion.get("failures") if isinstance(assertion, dict) else None
        if isinstance(failures, list) and failures:
            return str(failures[0])
    return ""


def ensure_case_slot(job: Job, index: int) -> dict[str, Any]:
    while len(job.cases) < index:
        next_index = len(job.cases) + 1
        job.cases.append(
            {
                "index": next_index,
                "name": f"用例 {next_index}",
                "case_no": "",
                "status": "pending",
                "duration": None,
                "failure": "",
            }
        )
    return job.cases[index - 1]


def apply_runner_event(job: Job, event: dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "run_started":
        raw_cases = event.get("cases")
        if not isinstance(raw_cases, list):
            return
        job.total_cases = int(event.get("total") or len(raw_cases))
        job.cases = []
        for fallback_index, raw_case in enumerate(raw_cases, 1):
            case = raw_case if isinstance(raw_case, dict) else {}
            index = int(case.get("index") or fallback_index)
            job.cases.append(
                {
                    "index": index,
                    "name": str(case.get("name") or f"用例 {index}"),
                    "case_no": str(case.get("case_no") or ""),
                    "status": "pending",
                    "duration": None,
                    "failure": "",
                }
            )
        return
    if event_type == "case_started":
        index = int(event.get("index") or 0)
        if index < 1:
            return
        job.total_cases = max(job.total_cases, int(event.get("total") or index))
        case = ensure_case_slot(job, index)
        case["status"] = "paused" if job.status == "paused" else "running"
        job.current_case_index = index
        return
    if event_type != "case_completed":
        return

    index = int(event.get("index") or 0)
    result = event.get("result")
    if index < 1 or not isinstance(result, dict):
        return
    job.total_cases = max(job.total_cases, int(event.get("total") or index))
    case = ensure_case_slot(job, index)
    passed = result.get("passed") is True
    case.update(
        {
            "name": str(result.get("name") or case["name"]),
            "case_no": str(result.get("case_no") or case["case_no"]),
            "status": "success" if passed else "failed",
            "duration": result.get("duration"),
            "failure": case_failure_summary(result),
        }
    )
    job.case_details[index] = result
    job.completed_cases = len(job.case_details)
    job.passed_cases = sum(item.get("passed") is True for item in job.case_details.values())
    job.failed_cases = job.completed_cases - job.passed_cases
    job.current_case_index = None


def handle_output_line(job: Job, line: str) -> None:
    if line.startswith(RUNNER_EVENT_PREFIX):
        try:
            event = json.loads(line[len(RUNNER_EVENT_PREFIX) :])
            if not isinstance(event, dict):
                raise TypeError("事件不是 JSON 对象")
            apply_runner_event(job, event)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            append_log(job, f"[WARN] 无法解析逐用例事件：{exc}\n")
        return
    append_log(job, line)
    match = REPORT_LINE_RE.match(line.strip())
    if not match:
        return
    report = Path(match.group(1)).resolve()
    try:
        report.relative_to(REPO_ROOT)
    except ValueError:
        return
    if report.is_file() and report not in job.reports:
        job.reports.append(report)


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
            if completed.returncode == 0:
                return
        except OSError:
            pass
        process.terminate()
        return
    try:
        if hasattr(os, "killpg") and hasattr(signal, "SIGCONT"):
            os.killpg(process.pid, signal.SIGCONT)
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except (AttributeError, OSError, ProcessLookupError):
        with suppress(OSError):
            process.terminate()


def pause_process(process: subprocess.Popen[str]) -> None:
    if (
        not hasattr(os, "killpg")
        or not hasattr(signal, "SIGSTOP")
        or not hasattr(signal, "SIGCONT")
    ):
        raise RunnerServerError("当前操作系统不支持无损暂停")
    if process.poll() is not None:
        raise RunnerServerError("任务进程已经结束")
    try:
        os.killpg(process.pid, signal.SIGSTOP)
    except (OSError, ProcessLookupError) as exc:
        raise RunnerServerError("暂停任务进程失败") from exc


def resume_process(process: subprocess.Popen[str]) -> None:
    if not hasattr(os, "killpg") or not hasattr(signal, "SIGCONT"):
        raise RunnerServerError("当前操作系统不支持恢复任务")
    if process.poll() is not None:
        raise RunnerServerError("任务进程已经结束")
    try:
        os.killpg(process.pid, signal.SIGCONT)
    except (OSError, ProcessLookupError) as exc:
        raise RunnerServerError("恢复任务进程失败") from exc


def mark_incomplete_case(job: Job, status: str, message: str) -> None:
    if job.current_case_index is None:
        return
    case = ensure_case_slot(job, job.current_case_index)
    if case["status"] in {"running", "paused"}:
        case["status"] = status
        case["failure"] = message
    job.current_case_index = None


def run_job(job: Job, condition: threading.Condition) -> None:
    return_code = 0
    try:
        for label, command, env_overrides in job.commands:
            with condition:
                if job.cancel_requested:
                    break
                append_log(job, f"\n=== {label} ===\n")
                process_env = os.environ.copy()
                process_env.update(env_overrides)
                process_env["PYTHONIOENCODING"] = "utf-8"
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=REPO_ROOT,
                        env=process_env,
                        start_new_session=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                    )
                finally:
                    env_overrides.clear()
                    process_env.clear()
                job.process = process
            assert process.stdout is not None
            with process.stdout:
                for line in process.stdout:
                    with condition:
                        handle_output_line(job, line)
            return_code = process.wait()
            with condition:
                job.process = None
            if return_code != 0:
                break
    except (OSError, subprocess.SubprocessError) as exc:
        return_code = 2
        with condition:
            append_log(job, f"\n执行异常：{exc}\n")

    with condition:
        clear_job_secrets(job)
        job.process = None
        job.return_code = return_code
        job.finished_at = time.time()
        if job.cancel_requested:
            append_log(job, "\n任务已由用户停止。\n")
            mark_incomplete_case(job, "cancelled", "任务在该用例执行期间被停止")
            job.status = "cancelled"
        else:
            if return_code != 0 and job.current_case_index is not None:
                mark_incomplete_case(job, "failed", "任务在该用例完成前异常退出")
            job.status = "success" if return_code == 0 else "failed"
        condition.notify_all()


def queue_worker(
    jobs: dict[str, Job],
    queue: list[str],
    condition: threading.Condition,
    stop_event: threading.Event,
) -> None:
    """严格按 queue 顺序串行消费已手动启动的任务。"""
    while not stop_event.is_set():
        with condition:
            job: Job | None = None
            for job_id in queue:
                candidate = jobs.get(job_id)
                if candidate is not None and candidate.status == "queued":
                    job = candidate
                    break
            if job is None:
                condition.wait(timeout=0.5)
                continue
            job.status = "running"
            job.started_at = time.time()
        run_job(job, condition)


def queue_position(job: Job, jobs: dict[str, Job], queue: Sequence[str]) -> int | None:
    pending = [
        job_id
        for job_id in queue
        if jobs.get(job_id) is not None
        and jobs[job_id].status in MOVABLE_STATUSES
    ]
    try:
        return pending.index(job.job_id) + 1
    except ValueError:
        return None


def serialize_job(
    job: Job,
    jobs: dict[str, Job],
    queue: Sequence[str],
    *,
    include_log: bool,
) -> dict[str, Any]:
    payload = {
        "job_id": job.job_id,
        "name": job.name,
        "dataset": job.dataset,
        "datasets": job.datasets or [job.dataset],
        "config": job.config,
        "status": job.status,
        "return_code": job.return_code,
        "queue_position": queue_position(job, jobs, queue),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "progress": {
            "total": job.total_cases,
            "completed": job.completed_cases,
            "passed": job.passed_cases,
            "failed": job.failed_cases,
            "current": job.current_case_index,
        },
        "cases": [
            {
                **case,
                "detail_url": (
                    f"/api/jobs/{job.job_id}/cases/{case['index']}"
                    if case["index"] in job.case_details
                    else ""
                ),
            }
            for case in job.cases
        ],
        "reports": [
            {
                "name": report.name,
                "url": f"/api/jobs/{job.job_id}/reports/{index}",
            }
            for index, report in enumerate(job.reports)
        ],
    }
    if include_log:
        payload["log"] = job.log
    return payload


def serialize_queue(jobs: dict[str, Job], queue: Sequence[str]) -> dict[str, Any]:
    return {
        "jobs": [
            serialize_job(jobs[job_id], jobs, queue, include_log=False)
            for job_id in queue
            if job_id in jobs
        ],
        "pause_supported": (
            hasattr(os, "killpg")
            and hasattr(signal, "SIGSTOP")
            and hasattr(signal, "SIGCONT")
        ),
    }


def move_waiting_job(
    job: Job,
    direction: str,
    jobs: dict[str, Job],
    queue: list[str],
) -> None:
    if job.status not in MOVABLE_STATUSES:
        raise RunnerServerError("只有待启动或已排队的任务可以调整顺序")
    movable = [job_id for job_id in queue if jobs[job_id].status in MOVABLE_STATUSES]
    index = movable.index(job.job_id)
    target = index - 1 if direction == "up" else index + 1
    if direction not in {"up", "down"}:
        raise RunnerServerError("移动方向只能是 up 或 down")
    if not 0 <= target < len(movable):
        return
    first_position = queue.index(movable[index])
    second_position = queue.index(movable[target])
    queue[first_position], queue[second_position] = queue[second_position], queue[first_position]


def prune_finished_jobs(jobs: dict[str, Job], queue: list[str]) -> None:
    while len(queue) >= MAX_JOBS:
        removable = min(
            (
                job_id
                for job_id in queue
                if jobs[job_id].status in TERMINAL_STATUSES
            ),
            key=lambda job_id: jobs[job_id].created_at,
            default=None,
        )
        if removable is None:
            raise RunnerServerError(f"任务列表最多保留 {MAX_JOBS} 条，请等待已有任务完成")
        queue.remove(removable)
        jobs.pop(removable, None)


def add_job_to_queue(jobs: dict[str, Job], queue: list[str], job: Job) -> None:
    """新任务置顶展示，并保持待启动状态。"""
    prune_finished_jobs(jobs, queue)
    jobs[job.job_id] = job
    queue.insert(0, job.job_id)


def start_ready_jobs(jobs: dict[str, Job], queue: Sequence[str]) -> int:
    """按当前列表顺序将所有待启动任务提交给串行工作线程。"""
    started = 0
    for job_id in queue:
        job = jobs.get(job_id)
        if job is None or job.status != "ready":
            continue
        job.status = "queued"
        append_log(job, "任务已手动启动，等待串行调度。\n")
        started += 1
    if started == 0:
        raise RunnerServerError("当前没有待启动任务")
    return started


def delete_job_record(jobs: dict[str, Job], queue: list[str], job_id: str) -> None:
    """删除未运行或已结束的任务记录，不删除已生成的报告文件。"""
    job = jobs.get(job_id)
    if job is None:
        raise RunnerServerError("任务不存在")
    if job.process is not None or job.status in {"running", "paused", "stopping"}:
        raise RunnerServerError("运行中的任务请先停止，结束后再删除记录")
    clear_job_secrets(job)
    if job_id in queue:
        queue.remove(job_id)
    jobs.pop(job_id, None)


def shutdown_jobs(
    jobs: dict[str, Job],
    condition: threading.Condition,
    stop_event: threading.Event,
    *,
    wait_timeout: float = 3,
) -> None:
    processes: list[subprocess.Popen[str]] = []
    stop_event.set()
    with condition:
        for job in jobs.values():
            if job.status in TERMINAL_STATUSES:
                continue
            job.cancel_requested = True
            clear_job_secrets(job)
            if job.process is None:
                job.status = "cancelled"
                job.finished_at = time.time()
                append_log(job, "\n页面服务关闭，任务已取消。\n")
            else:
                job.status = "stopping"
                processes.append(job.process)
        condition.notify_all()
    for process in processes:
        terminate_process(process)
    for process in processes:
        try:
            process.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            try:
                if hasattr(os, "killpg") and hasattr(signal, "SIGKILL"):
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (AttributeError, OSError, ProcessLookupError):
                with suppress(OSError):
                    process.kill()
            process.wait()


def make_handler(
    jobs: dict[str, Job],
    queue: list[str],
    condition: threading.Condition,
    runner_token: str,
    *,
    allow_non_dev: bool = False,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "LangGraphAutomationQueue/2.1"

        def add_security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")

        def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.add_security_headers()
            self.end_headers()
            self.wfile.write(body)

        def read_payload(self, *, required: bool = True) -> dict[str, Any]:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise RunnerServerError("请求大小不合法") from exc
            if content_length == 0 and not required:
                return {}
            if not 0 < content_length <= MAX_REQUEST_BYTES:
                raise RunnerServerError("请求大小不合法")
            try:
                payload = json.loads(self.rfile.read(content_length))
            except json.JSONDecodeError as exc:
                raise RunnerServerError("请求不是合法 JSON") from exc
            if not isinstance(payload, dict):
                raise RunnerServerError("页面参数必须是 JSON 对象")
            return payload

        def authorized(self) -> bool:
            if secrets.compare_digest(
                self.headers.get("X-Runner-Token", ""), runner_token
            ):
                return True
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "页面已失效，请刷新"})
            return False

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                config = build_public_config(load_runner_config_values())
                body = render_runner_html(runner_token, config).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.add_security_headers()
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "script-src 'self' 'unsafe-inline'; connect-src 'self'",
                )
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/config":
                self.send_json(
                    HTTPStatus.OK,
                    build_public_config(load_runner_config_values()),
                )
                return
            if path == "/api/jobs":
                with condition:
                    payload = serialize_queue(jobs, queue)
                self.send_json(HTTPStatus.OK, payload)
                return

            status_match = re.fullmatch(rf"/api/jobs/{JOB_ID_RE}", path)
            if status_match:
                with condition:
                    job = jobs.get(status_match.group(1))
                    payload = (
                        serialize_job(job, jobs, queue, include_log=True) if job else None
                    )
                if payload is None:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "任务不存在"})
                else:
                    self.send_json(HTTPStatus.OK, payload)
                return

            case_match = re.fullmatch(rf"/api/jobs/{JOB_ID_RE}/cases/(\d+)", path)
            if case_match:
                with condition:
                    job = jobs.get(case_match.group(1))
                    detail = (
                        job.case_details.get(int(case_match.group(2))) if job else None
                    )
                if detail is None:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "用例日志尚未生成"})
                else:
                    self.send_json(HTTPStatus.OK, {"case": detail})
                return

            report_match = re.fullmatch(
                rf"/api/jobs/{JOB_ID_RE}/reports/(\d+)", path
            )
            if report_match:
                with condition:
                    job = jobs.get(report_match.group(1))
                    index = int(report_match.group(2))
                    report = (
                        job.reports[index]
                        if job is not None and 0 <= index < len(job.reports)
                        else None
                    )
                if report is None or not report.is_file():
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "报告不存在"})
                    return
                body = report.read_bytes()
                content_type = mimetypes.guess_type(report.name)[0] or "text/plain"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.add_security_headers()
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

        def do_POST(self) -> None:
            if not self.authorized():
                return
            path = urlparse(self.path).path
            try:
                if path == "/api/chat/messages":
                    self.send_json(HTTPStatus.OK, send_chat_turn(self.read_payload()))
                    return

                if path == "/api/jobs":
                    job = build_job(
                        self.read_payload(), allow_non_dev=allow_non_dev
                    )
                    with condition:
                        add_job_to_queue(jobs, queue, job)
                        payload = serialize_job(job, jobs, queue, include_log=True)
                        condition.notify_all()
                    self.send_json(HTTPStatus.ACCEPTED, payload)
                    return

                if path == "/api/queue/start":
                    with condition:
                        start_ready_jobs(jobs, queue)
                        payload = serialize_queue(jobs, queue)
                        condition.notify_all()
                    self.send_json(HTTPStatus.ACCEPTED, payload)
                    return

                action_match = re.fullmatch(
                    rf"/api/jobs/{JOB_ID_RE}/(pause|resume|stop|move)", path
                )
                if not action_match:
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
                    return
                job_id, action = action_match.groups()
                process_to_stop: subprocess.Popen[str] | None = None
                with condition:
                    job = jobs.get(job_id)
                    if job is None:
                        raise RunnerServerError("任务不存在")
                    if action == "pause":
                        if job.status != "running" or job.process is None:
                            raise RunnerServerError("只有当前运行任务可以暂停")
                        pause_process(job.process)
                        job.status = "paused"
                        if job.current_case_index is not None:
                            ensure_case_slot(job, job.current_case_index)["status"] = "paused"
                        append_log(job, "\n任务已暂停；恢复后从当前执行点继续。\n")
                    elif action == "resume":
                        if job.status != "paused" or job.process is None:
                            raise RunnerServerError("任务当前不处于暂停状态")
                        resume_process(job.process)
                        job.status = "running"
                        if job.current_case_index is not None:
                            ensure_case_slot(job, job.current_case_index)["status"] = "running"
                        append_log(job, "\n任务已恢复。\n")
                    elif action == "stop":
                        if job.status in TERMINAL_STATUSES:
                            raise RunnerServerError("任务已经结束")
                        job.cancel_requested = True
                        if job.process is None:
                            clear_job_secrets(job)
                            job.status = "cancelled"
                            job.finished_at = time.time()
                            append_log(job, "\n等待任务已取消。\n")
                        else:
                            job.status = "stopping"
                            process_to_stop = job.process
                        condition.notify_all()
                    else:
                        direction = str(self.read_payload().get("direction") or "")
                        move_waiting_job(job, direction, jobs, queue)
                        condition.notify_all()
                    payload = serialize_job(job, jobs, queue, include_log=True)
                if process_to_stop is not None:
                    terminate_process(process_to_stop)
                self.send_json(HTTPStatus.ACCEPTED, payload)
            except RunnerServerError as exc:
                self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})

        def do_DELETE(self) -> None:
            if not self.authorized():
                return
            path = urlparse(self.path).path
            delete_match = re.fullmatch(rf"/api/jobs/{JOB_ID_RE}", path)
            if not delete_match:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
                return
            try:
                with condition:
                    delete_job_record(jobs, queue, delete_match.group(1))
                    condition.notify_all()
                self.send_json(HTTPStatus.OK, {"deleted": True})
            except RunnerServerError as exc:
                self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def run_self_test() -> int:
    dataset = str(Path("tests/fixtures/categories/golden_option_close_case.jsonl"))
    second_dataset = str(Path("tests/fixtures/categories/golden_option_inquiry_case.jsonl"))
    base_payload = {
        "task_name": "队列自检",
        "dataset": dataset,
        "run_langgraph": True,
        "push_wecom": False,
        "limit": 3,
        "langgraph_timeout": 300,
        "langgraph_retries": 2,
        "throttle_ms": 0,
        "user_id": "self-test-user",
        "room_id": "10821094351495088",
        "option_counterparties": json.dumps(
            DEFAULT_OPTION_COUNTERPARTIES, ensure_ascii=False
        ),
        "swap_counterparties": json.dumps(
            DEFAULT_SWAP_COUNTERPARTIES, ensure_ascii=False
        ),
    }
    checks: list[tuple[str, bool]] = []
    job = build_job(base_payload, job_id="a" * 32)
    command = job.commands[0][1]
    checks.append(
        (
            "旧版单数据集参数仍兼容并在入队前生成用例清单",
            job.dataset == dataset
            and job.datasets == [dataset]
            and job.total_cases == 3
            and len(job.cases) == 3
            and job.status == "ready",
        )
    )
    discovered_paths = {item["path"] for item in discover_datasets()}
    checks.append(
        (
            "页面只列出分类目录直属可执行数据集",
            dataset in discovered_paths and second_dataset in discovered_paths
            and all((REPO_ROOT / path).parent == DATASET_ROOT for path in discovered_paths),
        )
    )
    checks.append(("命令启用逐用例事件", "--runner-events" in command))
    checks.append(("LangGraph 回归命令不需要 Dify API key", "--api-key-env" not in command))
    multiple_job = build_job(
        {
            **base_payload,
            "dataset": None,
            "datasets": [dataset, second_dataset, dataset],
            "limit": 4,
        },
        job_id="8" * 32,
    )
    multiple_command = multiple_job.commands[0][1]
    data_arguments = [
        multiple_command[index + 1]
        for index, value in enumerate(multiple_command[:-1])
        if value == "--data"
    ]
    checks.append(
        (
            "一个任务可按顺序绑定多份数据集并去重",
            multiple_job.datasets == [dataset, second_dataset]
            and multiple_job.dataset == dataset
            and data_arguments == [dataset, second_dataset]
            and multiple_job.total_cases == 4,
        )
    )
    try:
        build_job({**base_payload, "dataset": None, "datasets": []})
        rejected_empty = False
    except RunnerServerError:
        rejected_empty = True
    checks.append(("拒绝未选择任何数据集的任务", rejected_empty))

    apply_runner_event(
        job,
        {
            "type": "run_started",
            "total": 2,
            "cases": [
                {"index": 1, "name": "用例一", "case_no": "case-1"},
                {"index": 2, "name": "用例二", "case_no": "case-2"},
            ],
        },
    )
    apply_runner_event(job, {"type": "case_started", "index": 1, "total": 2})
    apply_runner_event(
        job,
        {
            "type": "case_completed",
            "index": 1,
            "total": 2,
            "result": {
                "name": "用例一",
                "case_no": "case-1",
                "passed": True,
                "duration": 1.25,
                "conversation_url": "http://localhost/app/test/logs?conversation_id=1",
                "turns": [{"query": "输入", "answer": "输出", "assertion": {"failures": []}}],
            },
        },
    )
    checks.append(
        (
            "逐用例事件立即更新进度和详情",
            job.completed_cases == 1
            and job.passed_cases == 1
            and job.cases[0]["status"] == "success"
            and job.case_details[1]["turns"][0]["answer"] == "输出",
        )
    )

    jobs = {job.job_id: job}
    queue = [job.job_id]
    serialized = serialize_job(job, jobs, queue, include_log=False)
    checks.append(
        (
            "任务接口不返回密钥、返回数据集数组且提供用例详情地址",
            "app-self-test-secret" not in json.dumps(serialized, ensure_ascii=False)
            and serialized["datasets"] == [dataset]
            and bool(serialized["cases"][0]["detail_url"]),
        )
    )
    second = build_job({**base_payload, "task_name": "第二条"}, job_id="b" * 32)
    third = build_job({**base_payload, "task_name": "第三条"}, job_id="c" * 32)
    jobs.update({second.job_id: second, third.job_id: third})
    queue.extend([second.job_id, third.job_id])
    move_waiting_job(third, "up", jobs, queue)
    checks.append(("等待任务可以调整串行顺序", queue[-2:] == [third.job_id, second.job_id]))

    newest = build_job({**base_payload, "task_name": "最新任务"}, job_id="f" * 32)
    add_job_to_queue(jobs, queue, newest)
    checks.append(
        (
            "新任务置顶且不会自动进入执行队列",
            queue[0] == newest.job_id and newest.status == "ready",
        )
    )
    delete_job_record(jobs, queue, newest.job_id)
    checks.append(
        (
            "待启动任务记录可以删除",
            newest.job_id not in jobs and newest.job_id not in queue,
        )
    )

    if hasattr(os, "killpg") and hasattr(signal, "SIGSTOP") and hasattr(signal, "SIGCONT"):
        def fake_command(label: str, delay: float) -> list[str]:
            code = (
                "import json,time\n"
                f"prefix={RUNNER_EVENT_PREFIX!r}\n"
                "def emit(event):\n"
                " print(prefix+json.dumps(event,separators=(',',':')),flush=True)\n"
                f"emit({{'type':'run_started','total':1,'cases':[{{'index':1,'name':{label!r},'case_no':{label!r}}}]}})\n"
                "emit({'type':'case_started','index':1,'total':1})\n"
                f"time.sleep({delay!r})\n"
                f"emit({{'type':'case_completed','index':1,'total':1,'result':{{'name':{label!r},'case_no':{label!r},'passed':True,'duration':{delay!r},'conversation_id':'','conversation_url':'','turns':[]}}}})\n"
            )
            return [sys.executable, "-u", "-c", code]

        first_fake = Job(
            job_id="d" * 32,
            name="暂停自检一",
            dataset="self-test-1.jsonl",
            config={},
            commands=[("暂停自检一", fake_command("fake-1", 0.45), {})],
        )
        second_fake = Job(
            job_id="e" * 32,
            name="串行自检二",
            dataset="self-test-2.jsonl",
            config={},
            commands=[("串行自检二", fake_command("fake-2", 0.02), {})],
        )
        fake_jobs = {first_fake.job_id: first_fake, second_fake.job_id: second_fake}
        fake_queue = [first_fake.job_id, second_fake.job_id]
        fake_condition = threading.Condition(threading.Lock())
        fake_stop = threading.Event()
        fake_worker = threading.Thread(
            target=queue_worker,
            args=(fake_jobs, fake_queue, fake_condition, fake_stop),
            daemon=True,
        )
        fake_worker.start()
        time.sleep(0.12)
        with fake_condition:
            waited_for_manual_start = (
                first_fake.started_at is None and second_fake.started_at is None
            )
            start_ready_jobs(fake_jobs, fake_queue)
            fake_condition.notify_all()
        deadline = time.monotonic() + 2
        with fake_condition:
            while first_fake.process is None and time.monotonic() < deadline:
                fake_condition.wait(timeout=0.02)
            fake_process = first_fake.process
        pause_round_trip = False
        serial_finished = False
        try:
            if fake_process is not None:
                time.sleep(0.08)
                pause_process(fake_process)
                with fake_condition:
                    first_fake.status = "paused"
                    completed_at_pause = first_fake.completed_cases
                time.sleep(0.12)
                with fake_condition:
                    stayed_paused = (
                        first_fake.completed_cases == completed_at_pause
                        and second_fake.started_at is None
                    )
                    resume_process(fake_process)
                    first_fake.status = "running"
                deadline = time.monotonic() + 3
                with fake_condition:
                    while (
                        second_fake.status not in TERMINAL_STATUSES
                        and time.monotonic() < deadline
                    ):
                        fake_condition.wait(timeout=0.03)
                    pause_round_trip = (
                        stayed_paused
                        and first_fake.status == "success"
                        and first_fake.completed_cases == 1
                    )
                    serial_finished = (
                        second_fake.status == "success"
                        and second_fake.completed_cases == 1
                        and first_fake.finished_at is not None
                        and second_fake.started_at is not None
                        and second_fake.started_at >= first_fake.finished_at
                    )
        finally:
            fake_stop.set()
            with fake_condition:
                fake_condition.notify_all()
            for fake_job in fake_jobs.values():
                if fake_job.process is not None:
                    terminate_process(fake_job.process)
            fake_worker.join(timeout=2)
        checks.append(("运行任务可暂停并从原执行点恢复", pause_round_trip))
        checks.append(("调度线程严格串行执行任务", serial_finished))
        checks.append(("任务仅在手动启动后执行", waited_for_manual_start))
    else:
        checks.append(("当前平台不支持进程组暂停时明确降级", True))

    try:
        resolve_dataset("/etc/passwd")
        traversal_blocked = False
    except RunnerServerError:
        traversal_blocked = True
    checks.append(("拒绝读取仓库外测试集", traversal_blocked))
    config_names = ("LANGGRAPH_BASE",)
    saved_config_env = {name: os.environ.pop(name, None) for name in config_names}
    try:
        public_config = build_public_config(
            {
                "LANGGRAPH_BASE": "http://localhost:5001",
            }
        )
    finally:
        for name, value in saved_config_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    checks.append(("页面读取 LangGraph 默认地址", public_config["base_url"] == "http://localhost:5001"))
    rendered_html = render_runner_html("self-test-token", public_config)
    checks.append(
        (
            "页面不包含 Dify App ID 或 API key 输入",
            'id="workflow-id"' not in rendered_html
            and 'id="workflow-key"' not in rendered_html,
        )
    )
    checks.append(
        (
            "页面包含队列、手动启动、暂停和用例日志入口",
            'id="task-queue"' in rendered_html
            and 'id="start-queue-button"' in rendered_html
            and 'id="pause-button-template"' in rendered_html
            and 'id="case-log-dialog"' in rendered_html,
        )
    )
    checks.append(("正确识别仓库根目录", (REPO_ROOT / "pyproject.toml").is_file()))

    for label, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {label}")
    passed_count = sum(passed for _, passed in checks)
    print(f"自检结果：{passed_count}/{len(checks)}")
    return 0 if passed_count == len(checks) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动 LangGraph 自动化测试任务队列页面")
    parser.add_argument("--host", default="127.0.0.1", help="页面服务监听地址")
    parser.add_argument("--port", type=int, default=9001, help="本地页面端口")
    parser.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument(
        "--allow-non-dev",
        action="store_true",
        help="允许回归任务访问非 localhost/已知 dev 地址（仅限隔离测试环境）",
    )
    parser.add_argument("--self-test", action="store_true", help="运行离线自检后退出")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("--port 必须在 1024 到 65535 之间")
    if not (HTML_PATH.is_file() and LANGGRAPH_SCRIPT.is_file() and WECOM_SCRIPT.is_file()):
        raise SystemExit("页面或测试脚本不存在")

    jobs: dict[str, Job] = {}
    queue: list[str] = []
    condition = threading.Condition(threading.Lock())
    stop_event = threading.Event()
    worker = threading.Thread(
        target=queue_worker,
        args=(jobs, queue, condition, stop_event),
        daemon=True,
        name="langgraph-queue-worker",
    )
    worker.start()
    runner_token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(
            jobs,
            queue,
            condition,
            runner_token,
            allow_non_dev=args.allow_non_dev,
        ),
    )
    url = f"http://{args.host}:{args.port}"
    print(f"自动化测试任务队列：{url}")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info(
        "期权持仓 mock：需要固定持仓数据时，在仓库根目录另开终端启动：\n"
        ".venv/bin/python scripts/goats_api_mock/server.py --port 19027\n"
        "Java 管理页面中，仅将 GOATS_OPTION_CLOSING_OUT_CONTRACT_QUERY 地址配置为：\n"
        "http://127.0.0.1:19027/api/internal/agent/option/position"
    )
    print("按 Ctrl+C 停止服务。")
    if not args.no_open:
        webbrowser.open(url)
    interrupted = False
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        interrupted = True
    finally:
        shutdown_jobs(jobs, condition, stop_event)
        server.server_close()
        worker.join(timeout=4)
    if interrupted:
        print("\n页面服务已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
