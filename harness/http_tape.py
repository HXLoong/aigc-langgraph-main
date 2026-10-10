"""Private tool HTTP recordings; replay never has a network fallback.

Requests match method, URL, identity headers and body after removing credentials.
Repeated requests retain dispatch order even when their responses finish out of order.
Model HTTP, database access and attachment downloads are outside this transport.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import httpx

_FORMAT = {"format": "otc-tool-http-tape", "version": 1}
_IDENTITY_HEADERS = frozenset({
    "content-type", "accept", "agenttype", "agentid", "agentsubid", "tenant-id", "x-tenant-id",
})
_ERROR_TYPES = {kind.__name__: kind for kind in (
    httpx.TransportError, httpx.TimeoutException, httpx.ReadTimeout, httpx.WriteTimeout,
    httpx.ConnectTimeout, httpx.PoolTimeout, httpx.NetworkError, httpx.ConnectError,
    httpx.ReadError, httpx.WriteError, httpx.CloseError, httpx.ProtocolError,
    httpx.LocalProtocolError, httpx.RemoteProtocolError, httpx.ProxyError,
    httpx.UnsupportedProtocol,
)}


class TapeMissError(RuntimeError):
    """No unused matching receipt; never pass this request to a live transport."""


class TapeFormatError(ValueError):
    """An incomplete or unsupported recording cannot be safely replayed."""


def _secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "").replace("_", "")
    return normalized in {"key", "clientid", "apikey", "accesskey", "extappsalt"} or any(
        part in normalized for part in ("authorization", "password", "secret", "token", "signature", "cookie")
    )


def _public_url(url: httpx.URL) -> str:
    public = url.copy_with(username="", password="", fragment="")
    for key in url.params:
        if _secret_key(key):
            public = public.copy_set_param(key, "[REDACTED]")
    return str(public)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _secret_key(key) else _redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return _public_url(httpx.URL(value))
    return value


async def _request_data(request: httpx.Request) -> dict[str, Any]:
    raw = await request.aread()
    try:
        body: Any = {"json": _redact(json.loads(raw))}
    except (ValueError, UnicodeError):
        body = {"base64": base64.b64encode(raw).decode("ascii")}
    return {
        "method": request.method, "url": _public_url(request.url), "body": body,
        "headers": [[key, value] for key, value in request.headers.multi_items()
                    if key in _IDENTITY_HEADERS],
    }


def _key(request: dict[str, Any]) -> str:
    serialized = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _response(entry: dict[str, Any]) -> httpx.Response:
    response = entry["response"]
    return httpx.Response(
        response["status"], headers=response["headers"],
        stream=httpx.ByteStream(base64.b64decode(response["body_base64"], validate=True)),
    )


class RecordingTransport(httpx.AsyncBaseTransport):
    """Record actual upstream replies to an exclusive 0600 JSONL file."""

    def __init__(self, path: Path, upstream: httpx.AsyncBaseTransport | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self._file = os.fdopen(descriptor, "w", encoding="utf-8")
        self._upstream = upstream if upstream is not None else httpx.AsyncHTTPTransport()
        self._sequence = 0
        self._closed = False
        self._append(_FORMAT)

    def _append(self, entry: dict[str, Any]) -> None:
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._closed:
            raise RuntimeError("HTTP tape is closed")
        sequence, self._sequence = self._sequence, self._sequence + 1
        entry: dict[str, Any] = {"sequence": sequence, "request": await _request_data(request)}
        started = time.monotonic()
        try:
            response = await self._upstream.handle_async_request(request)
            try:
                headers = list(response.headers.multi_items())
                if response.is_stream_consumed:
                    raw = response.content
                    # Pre-buffered mock/custom transports may already have decompressed the body.
                    headers = [(key, value) for key, value in headers
                               if key not in {"content-encoding", "content-length"}]
                else:
                    raw = b"".join([chunk async for chunk in response.aiter_raw()])
                entry["response"] = {
                    "status": response.status_code,
                    "headers": [(key, value) for key, value in headers if not _secret_key(key)],
                    "body_base64": base64.b64encode(raw).decode("ascii"),
                }
            finally:
                await response.aclose()
        except (httpx.TransportError, TimeoutError, asyncio.CancelledError) as exc:
            entry["error"] = next(
                (kind.__name__ for kind in type(exc).__mro__ if kind.__name__ in _ERROR_TYPES),
                "CancelledError" if isinstance(exc, asyncio.CancelledError) else "TimeoutError",
            )
            entry["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            self._append(entry)
            raise
        entry["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        self._append(entry)
        # The live call receives its actual headers, including cookies. Only the
        # stored/replayed metadata excludes credentials.
        return httpx.Response(response.status_code, headers=headers, stream=httpx.ByteStream(raw))

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                await self._upstream.aclose()
            finally:
                self._file.close()


class ReplayTransport(httpx.AsyncBaseTransport):
    """Consume matching receipts once; no upstream transport exists in replay mode."""

    def __init__(self, path: Path) -> None:
        self._entries: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self._closed = False
        try:
            with path.open(encoding="utf-8") as stream:
                if json.loads(next(stream)) != _FORMAT:
                    raise TapeFormatError("unsupported HTTP tape format")
                entries = [json.loads(line) for line in stream if line.strip()]
            seen: set[int] = set()
            for entry in sorted(entries, key=lambda item: item["sequence"]):
                sequence = entry["sequence"]
                if not isinstance(sequence, int) or sequence in seen:
                    raise TapeFormatError("duplicate or invalid request sequence")
                seen.add(sequence)
                if ("response" in entry) == ("error" in entry):
                    raise TapeFormatError("recording must contain one response or transport failure")
                if "error" in entry and entry["error"] not in {*_ERROR_TYPES, "TimeoutError", "CancelledError"}:
                    raise TapeFormatError("unsupported recorded transport failure")
                if "response" in entry:
                    _response(entry)  # Validate bytes/status/headers before accepting any request.
                self._entries[_key(entry["request"])].append(entry)
        except (KeyError, TypeError, ValueError, StopIteration) as exc:
            raise TapeFormatError("invalid or incomplete HTTP tape") from exc

    @property
    def remaining(self) -> int:
        return sum(len(queue) for queue in self._entries.values())

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._closed:
            raise TapeMissError("HTTP replay transport is closed")
        request_key = _key(await _request_data(request))
        queue = self._entries.get(request_key)
        if not queue:
            raise TapeMissError(f"unrecorded or exhausted tool request fingerprint={request_key[:16]}")
        entry = queue.popleft()
        error = entry.get("error")
        if error == "TimeoutError":
            raise TimeoutError("recorded tool timeout")
        if error == "CancelledError":
            raise asyncio.CancelledError("recorded tool cancellation")
        if error is not None:
            raise _ERROR_TYPES[error]("recorded tool transport failure", request=request)
        return _response(entry)

    async def aclose(self) -> None:
        self._closed = True


class BorrowedTransport(httpx.AsyncBaseTransport):
    """A temporary client may close itself without closing the application-owned tape."""

    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self._transport = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        pass
