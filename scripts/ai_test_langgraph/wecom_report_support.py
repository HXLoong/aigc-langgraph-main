"""WeCom report helpers owned by the LangGraph regression workbench."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from regression_support import parse_dotenv_value

try:
    import certifi
except ImportError:  # pragma: no cover - stdlib CA remains available
    certifi = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPO_ROOT / "docs/testing/test-reports"
MAX_MARKDOWN_BYTES = 4096
MAX_REPORT_BYTES = 20 * 1024 * 1024


def truncate_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    ellipsis = "…"
    ellipsis_bytes = ellipsis.encode("utf-8")
    if max_bytes < len(ellipsis_bytes):
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    prefix = encoded[: max_bytes - len(ellipsis_bytes)].decode(
        "utf-8", errors="ignore"
    )
    return prefix + ellipsis


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs without overriding process variables."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = parse_dotenv_value(value)


def resolve_report(value: Path) -> Path:
    """Only allow Markdown reports below this repository's report directory."""
    report = value.expanduser()
    if not report.is_absolute():
        report = REPO_ROOT / report
    report = report.resolve()
    try:
        report.relative_to(REPORT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"报告必须位于 {REPORT_ROOT}") from exc
    if report.suffix.lower() != ".md" or not report.is_file():
        raise ValueError(f"Markdown 报告不存在: {report}")
    if report.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError(f"报告超过 {MAX_REPORT_BYTES // 1024 // 1024} MB，拒绝上传")
    return report


def load_json_report(report: Path) -> dict[str, Any]:
    json_path = report.with_suffix(".json")
    if not json_path.is_file():
        raise ValueError(f"缺少同名 JSON 报告: {json_path}")
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 报告解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON 报告顶层必须是对象")
    if not isinstance(payload.get("summary"), dict) or not isinstance(
        payload.get("cases"), list
    ):
        raise ValueError("JSON 报告缺少 summary 或 cases")
    return payload


def failure_reason(case: dict[str, Any]) -> str:
    error = str(case.get("error") or "").strip()
    if error:
        return error[:120]
    failures: list[str] = []
    turns = case.get("turns")
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            assertion = turn.get("assertion")
            if not isinstance(assertion, dict):
                continue
            turn_failures = assertion.get("failures")
            if isinstance(turn_failures, list):
                failures.extend(
                    str(item).strip()
                    for item in turn_failures
                    if str(item).strip()
                )
    return "；".join(failures[:2])[:120] or "未提供失败原因"


def build_markdown_summary(report: Path, payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    cases = [case for case in payload["cases"] if isinstance(case, dict)]
    passed = int(summary.get("passed") or 0)
    total = int(summary.get("total") or len(cases))
    failed = int(summary.get("failed") or max(total - passed, 0))
    average_duration = float(summary.get("avg_duration") or 0.0)
    duration = sum(float(case.get("duration") or 0.0) for case in cases)
    failures = [case for case in cases if not case.get("passed")]
    pass_rate = passed / total if total else 0.0
    color = (
        "info" if pass_rate >= 0.6 else "warning" if pass_rate < 0.4 else "comment"
    )
    header = (
        f"**LangGraph Test Report {time.strftime('%Y-%m-%d')}** "
        f"(耗时 {duration:.1f} 秒)\n"
        f'通过: <font color="{color}">**{passed}/{total}**</font>  '
        f"失败: **{failed}**  平均耗时: **{average_duration:.2f}s**"
    )
    footer = f"完整报告见下方附件：`{report.name}`"
    if failures:
        fixed_bytes = len(f"{header}\n\n失败 Top 10:\n\n{footer}".encode())
        remaining_bytes = MAX_MARKDOWN_BYTES - fixed_bytes - 16
        fail_lines: list[str] = []
        for case in failures[:10]:
            if remaining_bytes <= 16:
                break
            case_no = truncate_utf8(
                str(case.get("case_no") or case.get("name") or "未命名用例"), 96
            )
            prefix = f"> - `{case_no}` — "
            separator_bytes = 1 if fail_lines else 0
            available = remaining_bytes - separator_bytes
            prefix_bytes = len(prefix.encode())
            if available <= prefix_bytes:
                break
            reason = truncate_utf8(
                failure_reason(case), min(360, available - prefix_bytes)
            )
            line = prefix + reason
            fail_lines.append(line)
            remaining_bytes -= len(line.encode()) + separator_bytes
        failure_section = (
            f"失败 Top {len(fail_lines)}:\n" + "\n".join(fail_lines)
            if fail_lines
            else "失败 Top 0: 失败原因过长，请查看附件"
        )
    else:
        failure_section = "失败 Top 0: 无"
    content = f"{header}\n\n{failure_section}\n\n{footer}"
    if len(content.encode()) > MAX_MARKDOWN_BYTES:
        raise ValueError("企微 Markdown 汇总超过 4096 字节，无法安全截断")
    return content


def resolve_webhook() -> str:
    webhook = (
        os.environ.get("WECOM_TEST_WEBHOOK", "").strip()
        or os.environ.get("WECOM_BOT_WEBHOOK", "").strip()
    )
    if not webhook:
        raise ValueError(
            "正式推送时必须在仓库根目录 .env 配置 "
            "WECOM_TEST_WEBHOOK 或 WECOM_BOT_WEBHOOK"
        )
    parsed = urlparse(webhook)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if parsed.scheme != "https" or parsed.hostname != "qyapi.weixin.qq.com":
        raise ValueError("仅允许使用 qyapi.weixin.qq.com 的 HTTPS Webhook")
    if parsed.path != "/cgi-bin/webhook/send" or not query.get("key"):
        raise ValueError("企微 Webhook 路径或 key 参数不正确")
    return webhook


def build_upload_url(webhook: str) -> str:
    parsed = urlparse(webhook)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["type"] = "file"
    return urlunparse(
        parsed._replace(
            path="/cgi-bin/webhook/upload_media",
            query=urlencode(query),
        )
    )


def ssl_context(*, insecure: bool) -> ssl.SSLContext:
    cafile = certifi.where() if certifi is not None else None
    context = ssl.create_default_context(cafile=cafile)
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def post_json(
    webhook: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    insecure: bool,
) -> dict[str, Any]:
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl_context(insecure=insecure),
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("企微返回内容不是 JSON 对象")
        return result
    except urllib.error.HTTPError as exc:
        error = f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        error = f"网络错误: {exc.reason}"
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        error = f"响应解析失败: {exc}"
    return {"errcode": -1, "errmsg": error}


def upload_report(
    webhook: str,
    report: Path,
    *,
    timeout: float,
    retries: int,
    insecure: bool,
) -> dict[str, Any]:
    boundary = f"----langgraph-report-{time.time_ns()}"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="media"; filename="{report.name}"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
        ).encode()
        + report.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    upload_url = build_upload_url(webhook)
    last_error = "unknown error"
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            upload_url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=ssl_context(insecure=insecure),
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError("企微上传返回内容不是 JSON 对象")
            if result.get("errcode") == 0 and result.get("media_id"):
                return result
            last_error = (
                f"errcode={result.get('errcode')} errmsg={result.get('errmsg', '')}"
            )
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except urllib.error.URLError as exc:
            last_error = f"网络错误: {exc.reason}"
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            last_error = f"响应解析失败: {exc}"
        if attempt < retries:
            time.sleep(5)
    return {"errcode": -1, "errmsg": last_error}


def push_report(
    webhook: str,
    report: Path,
    summary: str,
    *,
    timeout: float,
    upload_timeout: float,
    retries: int,
    insecure: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    markdown_result = post_json(
        webhook,
        {"msgtype": "markdown", "markdown": {"content": summary}},
        timeout=timeout,
        insecure=insecure,
    )
    if markdown_result.get("errcode") != 0:
        return markdown_result, {}, {}
    upload_result = upload_report(
        webhook,
        report,
        timeout=upload_timeout,
        retries=retries,
        insecure=insecure,
    )
    media_id = upload_result.get("media_id")
    if upload_result.get("errcode") != 0 or not media_id:
        return markdown_result, upload_result, {}
    file_result = post_json(
        webhook,
        {"msgtype": "file", "file": {"media_id": media_id}},
        timeout=timeout,
        insecure=insecure,
    )
    return markdown_result, upload_result, file_result
