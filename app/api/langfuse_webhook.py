"""Langfuse Remote Experiment webhook：Langfuse UI 上点 Run，本机拉起一次数据集实验。

Langfuse 侧配置（Dataset → Start Experiment → ⚡ Custom Experiment）::

    URL             http://localhost:8000/v1/webhooks/langfuse
                    （Langfuse 跑在 Docker 里时 localhost 指向容器自身，改用 host.docker.internal）
    Sign requests   打开（密钥由 Langfuse 生成并只显示一次，填进 LANGFUSE_WEBHOOK_SECRET）
    Default config  {"ids": ["case-025", "case-026"], "concurrency": 1}
                    # 可选项 suite / ids / limit / concurrency，见 _ALLOWED_CONFIG_KEYS；
                    # ids 填 golden case id（也接受 dataset item 的 UUID），留空跑整个数据集

Langfuse 发来的请求::

    POST /v1/webhooks/langfuse
    {"projectId": "...", "datasetId": "...", "datasetName": "...", "payload": "<上面的 JSON 字符串>"}
    x-langfuse-signature: t=<unix秒>,v1=<hex>      # 签名内容 f"{t}.{raw_body}"，raw 字节

20 秒超时；任何 2xx 视为触发成功，非 2xx 会在 UI 上报错。

本模块只做三件事：验签、解析配置、点火。实验在子进程里跑 —— 一次几分钟且可能 OOM，
不能占着业务进程，也不能让它的异常影响在跑的业务请求。

开关 ``ENABLE_LANGFUSE_WEBHOOK`` 默认关闭（关闭时返回 404）；开启但未配置
``LANGFUSE_WEBHOOK_SECRET`` 时返回 503（fail-closed）。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["langfuse"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EVAL_SCRIPT = PROJECT_ROOT / "scripts" / "langfuse" / "langfuse_eval.py"
_RUN_LOG_DIR = PROJECT_ROOT / ".harness-runs"

#: 签名时间戳容忍窗口（秒）。触发是同步请求，正常秒级到达；窗口只用于挡重放。
_SIGNATURE_TOLERANCE_SECONDS = 300

#: 允许的 suite，与 scripts/langfuse/langfuse_eval.py 的 SUITES 对齐
_SUITES = ("intent", "business")
_ALLOWED_CONFIG_KEYS = frozenset({"suite", "ids", "limit", "concurrency"})

#: dataset 名 → 在跑的任务；同一 dataset 同时只允许一个 run，避免 UI 连点打爆后端
_running: dict[str, asyncio.Task[None]] = {}


def verify_signature(*, raw_body: bytes, header: str, secret: str) -> bool:
    """校验 x-langfuse-signature。

    raw_body 必须是收到的原始字节：先反序列化再 dumps 会改变字节（空格、键序、转义），
    签名必然对不上。
    """
    try:
        ts_pair, sig_pair = header.split(",", 1)
    except ValueError:  # 缺逗号 / 格式不对
        return False
    if "=" not in ts_pair or "=" not in sig_pair:
        return False

    timestamp = ts_pair.split("=", 1)[1]
    received_hex = sig_pair.split("=", 1)[1]

    try:
        if abs(time.time() - int(timestamp)) > _SIGNATURE_TOLERANCE_SECONDS:
            return False
    except ValueError:  # 时间戳不是整数
        return False

    expected_hex = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    try:
        # 按字节比较，兼容大写十六进制；compare_digest 保证常数时间
        return hmac.compare_digest(bytes.fromhex(received_hex), bytes.fromhex(expected_hex))
    except ValueError:  # received_hex 不是合法十六进制
        return False


def parse_config(raw: Any) -> dict[str, Any]:
    """把 payload 归一化成 dict。

    Langfuse UI 存的是 JSON 字符串（Dataset.remoteExperimentPayload 是 string），
    但 API 侧也可能直接给对象，两种都接受。未知字段直接报错 —— 手写 JSON 里的
    拼写错误必须让触发的人当场看见，不能静默忽略。
    """
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"payload 不是合法 JSON: {exc}") from exc
    else:
        parsed = raw
    if not isinstance(parsed, dict):
        raise ValueError("payload 必须是 JSON 对象")
    unknown = sorted(set(parsed) - _ALLOWED_CONFIG_KEYS)
    if unknown:
        raise ValueError(f"payload 含未知字段: {', '.join(unknown)}")
    return parsed


def build_eval_args(*, dataset_name: str, config: dict[str, Any]) -> list[str]:
    """拼 langfuse_eval.py 的命令行。

    批量评分固定 --no-judge：ADR 0005 规定评测只用确定性断言，不调用 LLM Judge。
    dataset 以 Langfuse 传来的 datasetName 为准，不从 config 取。
    """
    args = [str(_EVAL_SCRIPT), "--dataset", dataset_name]

    suite = config.get("suite")
    if suite is not None:
        if suite not in _SUITES:
            raise ValueError(f"suite 只能是 {' / '.join(_SUITES)}")
        args += ["--suite", str(suite)]

    ids = config.get("ids")
    if ids is not None:
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError("ids 必须是字符串数组")
        if ids:
            args += ["--ids", ",".join(ids)]

    for key, flag in (("limit", "--limit"), ("concurrency", "--concurrency")):
        value = config.get(key)
        if value is None:
            continue
        # bool 是 int 的子类，JSON true 不能当数字用
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{key} 必须是正整数")
        args += [flag, str(value)]

    args.append("--no-judge")
    return args


def _slug(name: str) -> str:
    """dataset 名（可能含 /）转成安全文件名片段。"""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:60]


def _spawn(*, args: list[str], dataset_name: str) -> tuple[subprocess.Popen[bytes], Path]:
    """起子进程。stdout/stderr 落 .harness-runs/，实验细节不回灌业务日志。

    用同步的 subprocess.Popen（调用方放工作线程）而不是 asyncio.create_subprocess_exec：
    Windows 上 uvicorn 带 --reload/--workers 时用的是 SelectorEventLoop，它的
    _make_subprocess_transport 直接抛 NotImplementedError（uvicorn/loops/asyncio.py:9）。
    Popen 与事件循环类型无关。
    """
    _RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = _RUN_LOG_DIR / f"langfuse-webhook-{stamp}-{_slug(dataset_name)}.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, *args],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    return proc, log_path


def _reap(proc: subprocess.Popen[bytes], dataset_name: str, log_path: Path) -> None:
    """回收子进程并释放 dataset 名额。"""
    try:
        code = proc.wait()
        logger.info(
            "langfuse remote experiment finished dataset=%s pid=%d code=%s log=%s",
            dataset_name,
            proc.pid,
            code,
            log_path,
        )
    finally:
        _running.pop(dataset_name, None)


@router.post("/langfuse", status_code=202)
async def trigger_remote_experiment(request: Request) -> dict[str, Any]:
    """接收 Langfuse 触发，点火后立即返回 202（Langfuse 侧 20 秒超时）。"""
    settings = get_settings()
    if not settings.enable_langfuse_webhook:
        raise HTTPException(status_code=404, detail="Not Found")
    if not settings.langfuse_webhook_secret:
        raise HTTPException(status_code=503, detail="LANGFUSE_WEBHOOK_SECRET 未配置")

    raw_body = await request.body()
    if not verify_signature(
        raw_body=raw_body,
        header=request.headers.get("x-langfuse-signature", ""),
        secret=settings.langfuse_webhook_secret,
    ):
        raise HTTPException(status_code=401, detail="签名校验失败")

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"请求体不是合法 JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

    dataset_name = body.get("datasetName")
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise HTTPException(status_code=400, detail="缺少 datasetName")

    try:
        args = build_eval_args(dataset_name=dataset_name, config=parse_config(body.get("payload")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    current = _running.get(dataset_name)
    if current is not None and not current.done():
        raise HTTPException(status_code=409, detail=f"{dataset_name} 已有实验在跑")

    if not _EVAL_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"评测脚本不存在: {_EVAL_SCRIPT}")

    # spawn 与 reap 都是同步阻塞调用，放工作线程，不占事件循环
    proc, log_path = await asyncio.to_thread(_spawn, args=args, dataset_name=dataset_name)
    _running[dataset_name] = asyncio.create_task(
        asyncio.to_thread(_reap, proc, dataset_name, log_path)
    )
    logger.info(
        "langfuse remote experiment started dataset=%s pid=%d log=%s",
        dataset_name,
        proc.pid,
        log_path,
    )
    return {
        "status": "accepted",
        "dataset": dataset_name,
        "pid": proc.pid,
        "log": str(log_path),
    }


__all__ = [
    "build_eval_args",
    "parse_config",
    "router",
    "verify_signature",
]
