#!/usr/bin/env python3
"""Run deterministic JSONL regression cases against aigc-langgraph."""

from __future__ import annotations

import argparse
import http.client
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
from regression_support import (  # noqa: E402 - sibling script module
    DEFAULT_BOT_NAME,
    DEFAULT_GUID,
    DEFAULT_OPTION_COUNTERPARTIES,
    DEFAULT_SWAP_COUNTERPARTIES,
    JudgeCallable,
    RunnerError,
    env_value,
    evaluate_response,
    load_cases,
    load_dotenv,
    parse_dotenv_value,
    parse_json_env,
    require_config,
    select_cases,
)

__all__ = ["parse_dotenv_value"]

DEFAULT_DATASET_DIR = REPO_ROOT / "tests/fixtures/categories"
REPORT_ROOT = REPO_ROOT / "docs/testing/test-reports"
DEFAULT_LANGGRAPH_BASE = "http://127.0.0.1:8000"
RUNNER_EVENT_PREFIX = "@@LANGGRAPH_RUNNER_EVENT@@"
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class TurnResult:
    scene: str
    query: str
    answer: str
    elapsed: float
    workflow_run_id: str
    assertion: Any
    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseResult:
    name: str
    case_no: str
    passed: bool
    duration: float
    conversation_id: str
    trace_id: str = ""
    trace_url: str = ""
    error: str = ""
    turns: list[TurnResult] = field(default_factory=list)


def default_report_dir() -> Path:
    return REPORT_ROOT / time.strftime("%Y%m%d")


def ensure_safe_target(
    base_url: str, allow_non_dev: bool, label: str = "LangGraph"
) -> None:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise RunnerError(f"{label}地址格式不正确：{base_url}")
    is_safe_default = host in {"localhost", "127.0.0.1"} or "smart-zone-dev" in host
    if not is_safe_default and not allow_non_dev:
        raise RunnerError(
            f"{label}地址不是已知 dev/localhost：{host}；"
            "如确认是隔离测试环境，显式添加 --allow-non-dev"
        )


def parse_workflow_response(payload: dict[str, Any]) -> tuple[str, str]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RunnerError("LangGraph 返回缺少 data 对象")
    status = str(data.get("status") or "")
    if status != "succeeded":
        error = str(data.get("error") or f"workflow status={status or 'unknown'}")
        raise RunnerError(error)
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        raise RunnerError("LangGraph 返回缺少 data.outputs 对象")
    answer = outputs.get("reply_text")
    if answer is None:
        answer = ""
    elif not isinstance(answer, str):
        answer = json.dumps(answer, ensure_ascii=False)
    return answer, str(payload.get("workflow_run_id") or data.get("id") or "")


class LangGraphClient:
    def __init__(
        self,
        *,
        base_url: str,
        user_id: str,
        room_id: str,
        bot_name: str,
        guid: str,
        option_counterparties: str,
        swap_counterparties: str,
        timeout: float,
        retries: int,
        throttle_ms: int,
        verify_tls: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.room_id = room_id
        self.bot_name = bot_name
        self.guid = guid
        self.option_counterparties = option_counterparties
        self.swap_counterparties = swap_counterparties
        self.timeout = timeout
        self.retries = retries
        self.throttle_ms = throttle_ms
        self.verify_tls = verify_tls
        self.last_outputs: dict[str, Any] = {}

    def build_payload(
        self,
        query: str,
        *,
        conversation_id: str,
        quote_content: str = "",
        at_bot: bool = True,
    ) -> dict[str, Any]:
        inputs = {
            "conversation_id": conversation_id,
            "message_id": str(time.time_ns()),
            "quote_appinfo": self.guid,
            "room_id": self.room_id,
            # aigc-langgraph/app/api/routes.py maps the Dify-compatible camelCase key.
            "userId": self.user_id,
            "guid": self.guid,
            "fast_query": "1" if "快速询价" in query else "0",
            "at_bot": "1" if at_bot else "0",
            "raw_content": query,
            "quote_content": quote_content,
            "existing_command": "0",
            "bot_name": self.bot_name,
            "option_counterparties": self.option_counterparties,
            "swap_counterparties": self.swap_counterparties,
        }
        return {"inputs": inputs, "response_mode": "blocking", "user": conversation_id}

    def send(
        self,
        query: str,
        *,
        conversation_id: str,
        quote_content: str = "",
        at_bot: bool = True,
        traceparent: str = "",
    ) -> tuple[str, str, str, float]:
        payload = self.build_payload(
            query,
            conversation_id=conversation_id,
            quote_content=quote_content,
            at_bot=at_bot,
        )
        headers = {"Content-Type": "application/json"}
        if traceparent:
            headers["traceparent"] = traceparent
        request = urllib.request.Request(
            f"{self.base_url}/v1/workflows/run",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        context = None
        if not self.verify_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        for attempt in range(self.retries + 1):
            if self.throttle_ms:
                time.sleep(self.throttle_ms / 1000.0)
            started = time.monotonic()
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout, context=context
                ) as response:
                    body_text = response.read().decode("utf-8", errors="replace")
                try:
                    response_payload = json.loads(body_text)
                except json.JSONDecodeError as exc:
                    raise RunnerError(
                        f"LangGraph 返回非 JSON：{body_text[:300]}"
                    ) from exc
                if not isinstance(response_payload, dict):
                    raise RunnerError("LangGraph 返回的 JSON 不是对象")
                data = response_payload.get("data")
                self.last_outputs = (
                    dict(data.get("outputs") or {}) if isinstance(data, dict) else {}
                )
                answer, workflow_run_id = parse_workflow_response(response_payload)
                return (
                    answer,
                    workflow_run_id,
                    conversation_id,
                    time.monotonic() - started,
                )
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code in RETRYABLE_HTTP_STATUSES and attempt < self.retries:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise RunnerError(f"LangGraph HTTP {exc.code}: {body[:300]}") from exc
            except urllib.error.URLError as exc:
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise RunnerError(f"LangGraph 请求失败：{exc}") from exc
            except http.client.IncompleteRead as exc:
                raise RunnerError(
                    f"LangGraph 请求失败：响应未完整返回（已读取 {len(exc.partial)} 字节）"
                ) from exc
        raise RunnerError("LangGraph 请求失败：unknown error")


def run_case(
    client: LangGraphClient,
    scenario: dict[str, Any],
    *,
    ignore_leading_mentions: bool,
    traceparent: str = "",
    judge: JudgeCallable | None = None,
) -> CaseResult:
    name = str(scenario["name"])
    case_no = str(scenario.get("caseNo") or "")
    conversation_id = f"ai-test-{uuid.uuid4().hex}"
    main_reply = ""
    previous_reply = ""
    turns: list[TurnResult] = []
    started = time.monotonic()
    error = ""
    turn_specs = [
        (
            str(scenario.get("scene") or "主场景"),
            scenario,
            bool(scenario.get("at_bot", True)),
        )
    ]
    for index, sub_scene in enumerate(scenario.get("sub_scenes") or [], 1):
        if not isinstance(sub_scene, dict) or not sub_scene.get("send_text"):
            raise RunnerError(f"用例 {name} 的第 {index} 个 sub_scene 缺少 send_text")
        turn_specs.append(
            (
                str(sub_scene.get("scene") or f"子场景{index}"),
                sub_scene,
                bool(sub_scene.get("at_bot", False)),
            )
        )
    try:
        for turn_index, (scene_name, turn_spec, at_bot) in enumerate(turn_specs):
            query = str(turn_spec.get("send_text") or "")
            answer, run_id, _, elapsed = client.send(
                query,
                conversation_id=conversation_id,
                quote_content=(
                    previous_reply
                    if turn_index and turn_spec.get("quote_previous") is True
                    else main_reply
                    if turn_index and "quote_previous" not in turn_spec
                    else ""
                ),
                at_bot=at_bot,
                traceparent=traceparent,
            )
            assertion = evaluate_response(
                answer,
                turn_spec,
                ignore_leading_mentions=ignore_leading_mentions,
                outputs=dict(client.last_outputs),
                judge=judge,
            )
            turns.append(
                TurnResult(
                    scene=scene_name,
                    query=query,
                    answer=answer,
                    elapsed=elapsed,
                    workflow_run_id=run_id,
                    assertion=assertion,
                    outputs=dict(client.last_outputs),
                )
            )
            if turn_index == 0:
                main_reply = answer
            previous_reply = answer
            if not assertion.passed:
                break
    except RunnerError as exc:
        error = str(exc)
    passed = (
        bool(turns)
        and not error
        and len(turns) == len(turn_specs)
        and all(turn.assertion.passed for turn in turns)
    )
    return CaseResult(
        name=name,
        case_no=case_no,
        passed=passed,
        duration=time.monotonic() - started,
        conversation_id=conversation_id,
        error=error,
        turns=turns,
    )


def run_case_isolated(
    client: LangGraphClient,
    scenario: dict[str, Any],
    *,
    ignore_leading_mentions: bool,
    traceparent: str = "",
    judge: JudgeCallable | None = None,
) -> CaseResult:
    started = time.monotonic()
    try:
        return run_case(
            client,
            scenario,
            ignore_leading_mentions=ignore_leading_mentions,
            traceparent=traceparent,
            judge=judge,
        )
    except Exception as exc:  # noqa: BLE001 - keep the remaining dataset running
        return CaseResult(
            name=str(scenario.get("name") or "未命名用例"),
            case_no=str(scenario.get("caseNo") or ""),
            passed=False,
            duration=time.monotonic() - started,
            conversation_id="",
            error=f"用例执行异常（{type(exc).__name__}: {exc}）",
        )


@dataclass
class CaseTrace:
    trace_id: str
    trace_url: str
    traceparent: str
    span: Any


def _case_turns(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        scenario,
        *[
            turn
            for turn in scenario.get("sub_scenes") or []
            if isinstance(turn, dict)
        ],
    ]


def build_case_trace_metadata(
    task_name: str, scenario: dict[str, Any]
) -> dict[str, str]:
    case_name = str(scenario.get("name") or "")
    return {
        "task_name": task_name,
        "dataset": str(scenario.get("_source") or ""),
        "case_id": str(scenario.get("caseNo") or case_name or "未命名用例"),
        "case_name": case_name,
        "category": str(scenario.get("category") or ""),
        "case_type": str(scenario.get("type") or ""),
        "source": str(scenario.get("source") or ""),
    }


def build_case_trace_input(scenario: dict[str, Any]) -> dict[str, Any]:
    turns = []
    for index, turn in enumerate(_case_turns(scenario), 1):
        if index == 1 or turn.get("quote_previous") is False:
            quote_source = "none"
        elif turn.get("quote_previous") is True:
            quote_source = "previous"
        else:
            quote_source = "main"
        item = {
            "turn": index,
            "scene": str(turn.get("scene") or ("主场景" if index == 1 else f"子场景{index - 1}")),
            "query": str(turn.get("send_text") or ""),
            "quote_source": quote_source,
        }
        assertions = {
            key: turn[key]
            for key in (
                "expected",
                "response_contains",
                "response_contains_any",
                "response_not_contains",
            )
            if turn.get(key) not in (None, "", [])
        }
        if assertions:
            item["assertions"] = assertions
        turns.append(item)
    return {"turns": turns}


def _ticker_codes(outputs: dict[str, Any]) -> list[str]:
    return [
        str(ticker.get("windCode") or ticker.get("wind_code"))
        for ticker in outputs.get("tickers") or []
        if isinstance(ticker, dict)
        and (ticker.get("windCode") or ticker.get("wind_code"))
    ]


def build_case_trace_output(
    scenario: dict[str, Any], result: CaseResult
) -> dict[str, Any]:
    planned_turns = _case_turns(scenario)
    failed_assertion = next(
        (
            (index, turn)
            for index, turn in enumerate(result.turns, 1)
            if not turn.assertion.passed
        ),
        None,
    )
    failure = None
    if result.error:
        failed_turn = min(len(result.turns) + 1, len(planned_turns))
        failed_spec = planned_turns[failed_turn - 1] if planned_turns else {}
        failure = {
            "turn": failed_turn,
            "scene": str(failed_spec.get("scene") or ""),
            "kind": "execution",
            "messages": [result.error],
        }
    elif failed_assertion:
        failed_turn, turn = failed_assertion
        failure = {
            "turn": failed_turn,
            "scene": turn.scene,
            "kind": "assertion",
            "messages": list(turn.assertion.failures),
        }

    turn_outputs = []
    structured_keys = (
        "place_params",
        "cancel_params",
        "confirm",
        "query_filter",
        "close_params",
    )
    for index, turn in enumerate(result.turns, 1):
        outputs = turn.outputs
        turn_outputs.append(
            {
                "turn": index,
                "scene": turn.scene,
                "workflow_run_id": turn.workflow_run_id,
                "product_type": outputs.get("product_type"),
                "intent": outputs.get("intent"),
                "ticker_codes": _ticker_codes(outputs),
                "needs_hitl": bool(outputs.get("ticker_hitl_candidates")),
                "structured_output": {
                    key: outputs[key]
                    for key in structured_keys
                    if outputs.get(key) not in (None, {}, [])
                },
                "assertion_passed": turn.assertion.passed,
                "assertion_failures": list(turn.assertion.failures),
                "reply_preview": turn.answer[:500],
            }
        )

    status = "passed" if result.passed else "execution_error" if result.error else "assertion_failed"
    return {
        "status": status,
        "passed": result.passed,
        "conversation_id": result.conversation_id,
        "progress": {
            "executed": len(result.turns),
            "total": len(planned_turns),
            "stopped_early": len(result.turns) < len(planned_turns),
        },
        "failure": failure,
        "turns": turn_outputs,
    }


def build_langfuse_client(values: dict[str, str]) -> Any | None:
    """按仓库 .env 创建测试用 LangFuse 客户端；不可用时不阻断回归。"""
    if env_value(values, "ENVIRONMENT", default="development") != "development":
        return None
    enabled = env_value(values, "ENABLE_LANGFUSE", default="false").lower()
    public_key = env_value(values, "LANGFUSE_PUBLIC_KEY")
    secret_key = env_value(values, "LANGFUSE_SECRET_KEY")
    if enabled not in {"1", "true", "yes", "on"} or not public_key or not secret_key:
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=env_value(
                values,
                "LANGFUSE_BASE_URL",
                "LANGFUSE_HOST",
                default="https://cloud.langfuse.com",
            ),
        )
    except Exception as exc:  # noqa: BLE001 - tracing 失败不阻断回归
        print(f"[WARN] LangFuse 用例 Trace 不可用：{exc}", file=sys.stderr)
        return None


@contextmanager
def open_case_trace(
    client: Any | None,
    *,
    task_name: str,
    scenario: dict[str, Any],
) -> Iterator[CaseTrace | None]:
    """为一条顶层测试用例创建父 Trace，所有对话轮次挂到该 Trace 下。"""
    if client is None:
        yield None
        return
    metadata = build_case_trace_metadata(task_name, scenario)
    try:
        observation = client.start_as_current_observation(
            name=f"{task_name}-{metadata['case_id']}",
            as_type="chain",
            input=build_case_trace_input(scenario),
            metadata=metadata,
        )
        span = observation.__enter__()
    except Exception as exc:  # noqa: BLE001 - tracing 失败不阻断回归
        print(f"[WARN] LangFuse 用例 Trace 创建失败：{exc}", file=sys.stderr)
        yield None
        return
    trace_id = str(span.trace_id)
    span_id = str(span.id)
    try:
        trace_url = client.get_trace_url(trace_id=trace_id) or ""
    except Exception as exc:  # noqa: BLE001 - 链接失败不影响 trace 上报
        print(f"[WARN] LangFuse Trace 链接不可用：{exc}", file=sys.stderr)
        trace_url = ""
    try:
        yield CaseTrace(
            trace_id=trace_id,
            trace_url=trace_url,
            traceparent=f"00-{trace_id}-{span_id}-01",
            span=span,
        )
    finally:
        observation.__exit__(*sys.exc_info())


def emit_runner_event(enabled: bool, event_type: str, **payload: Any) -> None:
    if enabled:
        print(
            RUNNER_EVENT_PREFIX
            + json.dumps(
                {"type": event_type, **payload},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            flush=True,
        )


def write_reports(
    results: Sequence[CaseResult], report_dir: Path, *, base_url: str
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sequence = 1
    while True:
        suffix = "" if sequence == 1 else f"-{sequence}"
        md_path = report_dir / f"langgraph-direct-{stamp}{suffix}.md"
        json_path = report_dir / f"langgraph-direct-{stamp}{suffix}.json"
        if not md_path.exists() and not json_path.exists():
            break
        sequence += 1
    passed = sum(result.passed for result in results)
    total = len(results)
    avg_duration = sum(result.duration for result in results) / total if total else 0
    report_payload = {
        "base_url": base_url,
        "generated_at": int(time.time()),
        "assertion_mode": "deterministic",
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "avg_duration": round(avg_duration, 3),
        },
        "cases": [asdict(result) for result in results],
    }
    json_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# LangGraph Test Report",
        "",
        f"- base_url: `{base_url}`",
        f"- 通过: **{passed}/{total}**",
        f"- 失败: **{total - passed}/{total}**",
        f"- 平均耗时: **{avg_duration:.2f}s**",
        "- 判定方式: `规则断言`",
        "",
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.extend(
            [
                f"## [{status}] {result.case_no or result.name}",
                "",
                f"- conversation_id: `{result.conversation_id}`",
                f"- tracing_id: `{result.trace_id or '-'}`",
                f"- duration: `{result.duration:.2f}s`",
            ]
        )
        if result.error:
            lines.append(f"- error: {result.error}")
        lines.append("")
        for turn in result.turns:
            lines.extend(
                [
                    f"### {turn.scene}",
                    "",
                    *[f"- {failure}" for failure in turn.assertion.failures],
                    "",
                    "#### 输入",
                    "",
                    "```text",
                    turn.query,
                    "```",
                    "",
                    "#### 实际回复",
                    "",
                    "```text",
                    turn.answer,
                    "```",
                    "",
                    "#### LangGraph outputs",
                    "",
                    "```json",
                    json.dumps(turn.outputs, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="直接调用 aigc-langgraph，并用确定性规则校验 JSONL 用例"
    )
    parser.add_argument("--data", action="append", default=[], help="JSONL 文件，可重复；缺省按文件名排序加载 tests/fixtures/categories/ 直属 JSONL")
    parser.add_argument("--task-name", default="")
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--case-no", action="append", default=[])
    parser.add_argument("--keyword", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--bot-name", default="")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--throttle-ms", type=int, default=0)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--allow-non-dev", action="store_true")
    parser.add_argument("--keep-expected-mentions", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--report-dir", default=str(default_report_dir()))
    parser.add_argument("--runner-events", action="store_true", help=argparse.SUPPRESS)
    return parser


def resolve_paths(raw_paths: Sequence[str]) -> list[Path]:
    if not raw_paths:
        return sorted(DEFAULT_DATASET_DIR.glob("*.jsonl"))
    return [
        path if path.is_absolute() else Path.cwd() / path
        for path in (Path(value).expanduser() for value in raw_paths)
    ]


def run_self_test() -> int:
    client = LangGraphClient(
        base_url=DEFAULT_LANGGRAPH_BASE,
        user_id="self-test-user",
        room_id="self-test-room",
        bot_name=DEFAULT_BOT_NAME,
        guid=DEFAULT_GUID,
        option_counterparties="[]",
        swap_counterparties="[]",
        timeout=1,
        retries=0,
        throttle_ms=0,
        verify_tls=True,
    )
    payload = client.build_payload(
        "确认下单",
        conversation_id="conv-1",
        quote_content="上一轮回复",
    )
    checks = [
        ("使用 workflow run 协议", payload["user"] == "conv-1"),
        ("传递企微用户上下文", payload["inputs"]["userId"] == "self-test-user"),
        (
            "读取 reply_text",
            parse_workflow_response(
                {
                    "workflow_run_id": "run-1",
                    "data": {"status": "succeeded", "outputs": {"reply_text": "ok"}},
                }
            )
            == ("ok", "run-1"),
        ),
        ("正确识别仓库根目录", (REPO_ROOT / "pyproject.toml").is_file()),
        ("默认分类数据可以加载", bool(load_cases(resolve_paths([])))),
    ]
    for label, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {label}")
    return 0 if all(passed for _, passed in checks) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    try:
        dataset_paths = resolve_paths(args.data)
        cases = load_cases(dataset_paths)
        selected = select_cases(
            cases,
            names=args.name,
            case_nos=args.case_no,
            keyword=args.keyword,
            limit=args.limit,
            shuffle=args.shuffle,
            seed=args.seed,
        )
        if not selected:
            raise RunnerError("筛选后没有可执行用例")
        print(f"数据校验通过：加载 {len(cases)} 条，选中 {len(selected)} 条")
        if args.list or args.dry_run:
            for case in selected:
                print(f"- {case.get('caseNo') or '-'}  {case['name']}")
            return 0
        if args.timeout <= 0 or args.retries < 0 or args.throttle_ms < 0:
            raise RunnerError("timeout 必须大于 0，retries/throttle-ms 不能小于 0")
        dotenv = load_dotenv(REPO_ROOT / ".env")
        base_url = args.base_url or env_value(
            dotenv, "LANGGRAPH_BASE", default=DEFAULT_LANGGRAPH_BASE
        )
        ensure_safe_target(base_url, args.allow_non_dev)
        client = LangGraphClient(
            base_url=base_url,
            user_id=require_config(env_value(dotenv, "EVAL_USER_ID"), "EVAL_USER_ID"),
            room_id=require_config(env_value(dotenv, "EVAL_ROOM_ID"), "EVAL_ROOM_ID"),
            bot_name=args.bot_name
            or env_value(dotenv, "LANGGRAPH_BOT_NAME", "DIFY_BOT_NAME", default=DEFAULT_BOT_NAME),
            guid=env_value(dotenv, "LANGGRAPH_EVAL_GUID", "DIFY_EVAL_GUID", default=DEFAULT_GUID),
            option_counterparties=parse_json_env(
                env_value(dotenv, "LANGGRAPH_OPTION_COUNTERPARTIES", "DIFY_OPTION_COUNTERPARTIES"),
                DEFAULT_OPTION_COUNTERPARTIES,
                "LANGGRAPH_OPTION_COUNTERPARTIES",
            ),
            swap_counterparties=parse_json_env(
                env_value(dotenv, "LANGGRAPH_SWAP_COUNTERPARTIES", "DIFY_SWAP_COUNTERPARTIES"),
                DEFAULT_SWAP_COUNTERPARTIES,
                "LANGGRAPH_SWAP_COUNTERPARTIES",
            ),
            timeout=args.timeout,
            retries=args.retries,
            throttle_ms=args.throttle_ms,
            verify_tls=not args.insecure,
        )
        langfuse_client = build_langfuse_client(dotenv)
        judge = None
        try:
            from line_judge import build_line_judge

            judge = build_line_judge()
        except Exception as exc:  # noqa: BLE001 - 裁判不可用不阻断回归
            print(f"[WARN] LLM 断言裁判不可用：{exc}", file=sys.stderr)
        print(f"LLM 断言裁判：{'已启用' if judge is not None else '未启用（纯确定性断言）'}")
        task_name = args.task_name.strip() or dataset_paths[0].stem
        emit_runner_event(args.runner_events, "run_started", total=len(selected))
        results = []
        for index, scenario in enumerate(selected, 1):
            emit_runner_event(args.runner_events, "case_started", index=index, total=len(selected))
            with open_case_trace(
                langfuse_client, task_name=task_name, scenario=scenario
            ) as case_trace:
                result = run_case_isolated(
                    client,
                    scenario,
                    ignore_leading_mentions=not args.keep_expected_mentions,
                    traceparent=case_trace.traceparent if case_trace else "",
                    judge=judge,
                )
                if case_trace:
                    result.trace_id = case_trace.trace_id
                    result.trace_url = case_trace.trace_url
                    try:
                        case_trace.span.update(
                            metadata={
                                **build_case_trace_metadata(task_name, scenario),
                                "conversation_id": result.conversation_id,
                            },
                            output=build_case_trace_output(scenario, result),
                        )
                    except Exception as exc:  # noqa: BLE001 - tracing 不改变回归结果
                        print(
                            f"[WARN] LangFuse 用例结果写入失败：{exc}",
                            file=sys.stderr,
                        )
            results.append(result)
            emit_runner_event(
                args.runner_events,
                "case_completed",
                index=index,
                total=len(selected),
                result=asdict(result),
            )
            print(
                f"[{index}/{len(selected)}] {'PASS' if result.passed else 'FAIL'} "
                f"{result.name} ({result.duration:.2f}s)"
            )
        if not args.no_report:
            md_path, json_path = write_reports(
                results, Path(args.report_dir).expanduser(), base_url=base_url
            )
            print(f"Markdown report: {md_path}")
            print(f"JSON report: {json_path}")
        passed = sum(result.passed for result in results)
        if langfuse_client is not None:
            try:
                langfuse_client.flush()
            except Exception as exc:  # noqa: BLE001 - tracing 不改变回归结果
                print(f"[WARN] LangFuse Trace 刷新失败：{exc}", file=sys.stderr)
        emit_runner_event(
            args.runner_events,
            "run_completed",
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
        )
        print(f"通过: {passed}/{len(results)}  失败: {len(results) - passed}/{len(results)}")
        return 0 if passed == len(results) else 1
    except RunnerError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
