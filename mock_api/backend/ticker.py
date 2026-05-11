"""标的与交易对手路由：

- `/admin-api/integration/securities-instrument/select` — 标的查询（GET + body）
- `/admin-api/counterparty/info/list` — 交易对手列表
- `/admin-api/counterparty/info/instrument-inference-prompt` — 推断 prompt 配置
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from mock_api.backend.fixtures import (
    COUNTERPARTIES,
    INSTRUMENT_INFERENCE_PROMPT,
    SECURITIES_DICT,
)
from mock_api.backend.schemas import (
    CounterpartyInfoReqVO,
    KeywordItem,
    SecuritiesInstrumentReqVO,
    common_ok,
)

router = APIRouter(tags=["mock-backend-ticker"])


# ============================================================
# 工具：词典匹配 + 评分
# ============================================================


def _normalize_hk(code: str) -> str:
    """港股代码补零归一化：00700.HK → 0700.HK，700 → 0700"""
    if "." in code:
        parts = code.split(".")
        if parts[1].upper() == "HK":
            num = parts[0].lstrip("0") or "0"
            return f"{int(num):04d}.HK"
    return code


def _score(item: dict[str, Any], keyword: str, is_full: bool) -> int | None:
    """返回相关度分数（越小越相关），不匹配返回 None。"""
    kw = _normalize_hk(keyword.strip())
    if not kw:
        return None
    wc = _normalize_hk(item["windCode"])
    short_desc = item["insShtDesc"]
    long_desc = item["insLngDesc"]

    if is_full:
        if wc.upper() == kw.upper() or wc.split(".")[0] == kw:
            return 0
        return None

    # 模糊：精确匹配 < 前缀 < 包含
    if kw == wc or kw == short_desc:
        return 0
    if kw.upper() in (wc.upper(),) or kw == short_desc:
        return 1
    if (
        wc.upper().startswith(kw.upper())
        or short_desc.startswith(kw)
        or long_desc.startswith(kw)
    ):
        return 5
    if (
        kw.upper() in wc.upper()
        or kw in short_desc
        or kw in long_desc
    ):
        return 10
    return None


def _search_securities(keywords: list[KeywordItem]) -> list[dict[str, Any]]:
    """按 keywordItems 匹配，按 relevanceScore 升序返回。"""
    bucket: dict[str, tuple[int, dict[str, Any]]] = {}
    for k in keywords:
        for item in SECURITIES_DICT:
            score = _score(item, k.keyword, bool(k.isFull))
            if score is None:
                continue
            wc = item["windCode"]
            existing = bucket.get(wc)
            if existing is None or score < existing[0]:
                bucket[wc] = (score, item)

    out: list[dict[str, Any]] = []
    for score, item in sorted(bucket.values(), key=lambda x: x[0]):
        out.append(
            {
                "id": item["id"],
                "windCode": item["windCode"],
                "insShtDesc": item["insShtDesc"],
                "insLngDesc": item["insLngDesc"],
                "insFamily": item["insFamily"],
                "currency": item["currency"],
                "exchange": item["exchange"],
                "transactionTypeList": ",".join(item["transactionTypeLists"]),
                "transactionTypeLists": item["transactionTypeLists"],
                "relevanceScore": score,
            }
        )
    return out


# ============================================================
# 路由
# ============================================================


@router.api_route(
    "/admin-api/integration/securities-instrument/select",
    methods=["GET", "POST"],
)
async def securities_instrument_select(request: Request) -> dict[str, Any]:
    """标的查询（GET + body 是 Java 端原生的不规范写法，这里 GET/POST 都接）。

    入参 `SecuritiesInstrumentOpenApiReqVO`: `{keywordItems: [{keyword, isFull}]}`
    出参 `list[SecuritiesInstrumentOpenApiRespVO]`
    """
    raw = await request.body()
    try:
        body = __import__("json").loads(raw) if raw else {}
    except Exception:
        body = {}
    req = SecuritiesInstrumentReqVO.model_validate(body or {})
    return common_ok(_search_securities(req.keywordItems))


@router.get("/admin-api/counterparty/info/list")
async def counterparty_info_list(
    type: str = Query("TRS", min_length=1),
    roomId: str = Query("mock-room", min_length=1),
    messageId: int | None = Query(None),
    orderId: str | None = Query(None),
    userId: str | None = Query(None),
) -> dict[str, Any]:
    """交易对手列表（GET /admin-api/counterparty/info/list）。

    Java 端是 `@Valid CounterpartyInfoRespVO`（命名沿用），实际是 ReqVO，
    `type` + `roomId` 必填。
    """
    # 触发 Pydantic 校验确保参数合法（业务行为：当前 mock 不区分 type/roomId）
    CounterpartyInfoReqVO(
        type=type, roomId=roomId, messageId=messageId, orderId=orderId, userId=userId
    )
    return common_ok(COUNTERPARTIES)


@router.get("/admin-api/counterparty/info/instrument-inference-prompt")
async def instrument_inference_prompt() -> dict[str, Any]:
    """推断 prompt 配置（GET /admin-api/counterparty/info/instrument-inference-prompt）。"""
    return common_ok(INSTRUMENT_INFERENCE_PROMPT)
