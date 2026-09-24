#!/usr/bin/env python3
"""独立运行的 GOATS 期权持仓、开仓和平仓 mock，不连接业务服务或数据库。"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import copy, deepcopy
from datetime import datetime
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import FastAPI, Header, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_DATA_FILE = Path(__file__).with_name("option_positions.json")
logger = logging.getLogger(__name__)


class ChineseLogFormatter(logging.Formatter):
    """本地化服务生命周期提示，保留原始参数、异常堆栈和未知日志。"""

    MESSAGES = {
        "Started server process [%d]": "进程已启动，进程号：%d",
        "Waiting for application startup.": "正在初始化服务……",
        "Application startup complete.": "服务初始化完成",
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)": (
            "监听地址：%s://%s:%d（按 Ctrl+C 停止服务）"
        ),
        "Uvicorn running on %s://[%s]:%d (Press CTRL+C to quit)": (
            "监听地址：%s://[%s]:%d（按 Ctrl+C 停止服务）"
        ),
        "Shutting down": "正在停止服务……",
        "Waiting for application shutdown.": "正在清理服务资源……",
        "Application shutdown complete.": "服务资源清理完成",
        "Finished server process [%d]": "进程已退出，进程号：%d",
        "Application startup failed. Exiting.": "服务启动失败，正在退出",
        "Application shutdown failed. Exiting.": "服务停止失败，正在退出",
    }
    LEVELS = {"DEBUG": "调试", "INFO": "信息", "WARNING": "警告", "ERROR": "错误", "CRITICAL": "严重"}

    def format(self, record: logging.LogRecord) -> str:
        localized = copy(record)
        localized.levelname = self.LEVELS.get(record.levelname, record.levelname)
        if record.name.startswith("uvicorn") and isinstance(record.msg, str):
            localized.msg = self.MESSAGES.get(record.msg, record.msg)
        return super().format(localized)


def logging_config() -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "chinese": {
                "()": ChineseLogFormatter,
                "fmt": "[%(levelname)s] GOATS 期权 Mock 服务 | %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "chinese",
                "stream": "ext://sys.stderr",
            }
        },
        "loggers": {
            name: {"handlers": ["console"], "level": "INFO", "propagate": False}
            for name in (__name__, "uvicorn", "uvicorn.error", "uvicorn.access")
        },
    }


class PositionFilter(BaseModel):
    wind_code: str | None = Field(default=None, alias="windCode")
    ins_family_list: list[str] | None = Field(default=None, alias="insFamilyList")
    contract_type_list: list[str] | None = Field(default=None, alias="contractTypeList")
    contract_sub_type_list: list[str] | None = Field(default=None, alias="contractSubTypeList")
    allow_close_out: bool | None = Field(default=None, alias="allowCloseOut")

    @field_validator("allow_close_out", mode="before")
    @classmethod
    def empty_boolean_is_unrestricted(cls, value: Any) -> Any:
        return None if value == "" else value

    def matches(self, position: dict[str, Any]) -> bool:
        if self.wind_code and position["windcode"] != self.wind_code:
            return False
        for values, field in (
            (self.ins_family_list, "insFamily"),
            (self.contract_type_list, "contractType"),
            (self.contract_sub_type_list, "contractSubType"),
        ):
            if values and position.get(field) not in values:
                return False
        return not self.allow_close_out or position["allowCloseOut"] is True


class PositionQuery(BaseModel):
    filter: PositionFilter | None = Field(default_factory=PositionFilter)
    page_num: int = Field(default=1, ge=1, alias="pageNum")
    page_size: int = Field(default=0, ge=0, alias="pageSize")


class CloseRequest(BaseModel):
    contract_code: str = Field(alias="contractCode", min_length=1)
    notional_delta: Decimal = Field(alias="notionalDelta", gt=0)
    algo_type: Literal["LIMIT", "MARKET", "POV", "TWAP"] = Field(alias="algoType")
    price: Decimal | None = Field(default=None, gt=0)
    pov_ratio: Decimal | None = Field(default=None, alias="povRatio", gt=0, le=1)
    algo_start_time: str | None = Field(default=None, alias="algoStartTime")
    algo_end_time: str | None = Field(default=None, alias="algoEndTime")


class OrderFilter(BaseModel):
    trade_date: str | None = Field(default=None, alias="tradeDate")
    contract_code: str | None = Field(default=None, alias="contractCode")
    key_stock_order_id: int | None = Field(default=None, alias="keyStockOrderId")
    contract_type: str | None = Field(default=None, alias="contractType")


class OrderQuery(BaseModel):
    filter: OrderFilter | None = Field(default_factory=OrderFilter)
    page_num: int = Field(default=1, ge=1, alias="pageNum")
    page_size: int = Field(default=0, ge=0, alias="pageSize")


class WithdrawRequest(BaseModel):
    key_stock_order_id: int = Field(alias="keyStockOrderId", gt=0)


class OpenRequest(BaseModel):
    id: int = Field(gt=0)
    contract_type: str = Field(alias="contractType", min_length=1)
    direction: Literal["CALL", "PUT"]
    trade_direction: Literal["BUY", "SELL"] = Field(alias="tradeDirection")
    quotation_order_type: str = Field(alias="quotationOrderType", min_length=1)
    open_position_type: Literal["MARKET_PRICE", "LIMIT_PRICE", "POV", "TWAP"] = Field(
        alias="openPositionType"
    )
    collateral_notional: Decimal = Field(alias="collateralNotional", gt=0)
    short_name: str = Field(alias="shortName", min_length=1)
    initial_underlying_price_order: Decimal | None = Field(
        default=None, alias="initialUnderlyingPriceOrder", gt=0
    )
    algorithm_order_vol: Decimal | None = Field(default=None, alias="algorithmOrderVol", gt=0)
    algorithm_order_start_time: str | None = Field(default=None, alias="algorithmOrderStartTime")
    algorithm_order_end_time: str | None = Field(default=None, alias="algorithmOrderEndTime")


class SwapRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    wind_code: str = Field(alias="windCode", min_length=1)
    transaction_type: str = Field(alias="transactionType", min_length=1)
    order_direction: str = Field(alias="orderDirection", min_length=1)
    price_type: str = Field(alias="priceType", min_length=1)
    order_type: str = Field(alias="orderType", min_length=1)
    short_name: str = Field(alias="shortName", min_length=1)
    quantity: Decimal | None = Field(default=None, gt=0)
    notional: Decimal | None = Field(default=None, gt=0)
    notional_currency: str | None = Field(default=None, alias="notionalCurrency")
    price: Decimal | None = Field(default=None, gt=0)
    fix_price: Decimal | None = Field(default=None, alias="fixPrice", gt=0)


class SwapStatusRequest(BaseModel):
    key_order_id: int = Field(alias="keyOrderId", gt=0)


class SwapQuery(BaseModel):
    key_order_id_list: list[int] | None = Field(default=None, alias="keyOrderIdList")


class SwapWithdrawRequest(BaseModel):
    order_list: list[int] = Field(alias="orderList", min_length=1)


def goats_response(data: Any = None, *, error: str | None = None) -> dict[str, Any]:
    return {
        "errMsg": error,
        "errCode": {
            "code": 403 if error else 200,
            "chs": "请求失败" if error else "请求成功",
            "eng": "FAIL_REQUEST" if error else "SUCCESS_REQUEST",
        },
        "data": jsonable_encoder(data),
    }


class MockOpening:
    """模拟审核及异步撤单；只生成模拟编号，不连接真实询价或成交系统。"""

    def __init__(self) -> None:
        self.orders: dict[int, dict[str, Any]] = {}
        self.owners: dict[int, tuple[str, str | None]] = {}
        self.applications: dict[str, int] = {}
        self.withdrawals: dict[str, int] = {}
        # Java 的审核订单号字段是 Integer，不能复用平仓的微秒级 Long 编号。
        self.identifiers = count(1_000_000_000 + int(time.time()) % 1_000_000_000)

    def visible(self, identifier: int | None, agent: str, user: str | None) -> bool:
        owner = self.owners.get(identifier) if identifier is not None else None
        return owner is not None and owner[0] == agent and (user is None or owner[1] == user)

    def place(self, request: OpenRequest, agent: str, user: str | None) -> dict[str, Any]:
        if request.open_position_type == "LIMIT_PRICE" and request.initial_underlying_price_order is None:
            return goats_response(error="限价单缺少价格")
        if request.open_position_type == "POV" and request.algorithm_order_vol is None:
            return goats_response(error="POV 缺少跟量比例")
        if request.open_position_type == "TWAP" and not (
            request.algorithm_order_start_time and request.algorithm_order_end_time
        ):
            return goats_response(error="TWAP 缺少起止时间")
        identifier = next(self.identifiers)
        application_id = f"MOCK-OPEN-{identifier}"
        now = datetime.now()
        self.orders[identifier] = {
            "trdGoatsOptionOrder": {
                "keyStockOrderId": identifier, "keyGoatsOptionOrderId": identifier,
                "keyRfqId": request.id, "orderStatus": "TOTRADE_PENDING",
                "tradeDate": now.strftime("%Y-%m-%d"),
                "tradeTime": now.strftime("%Y-%m-%d %H:%M:%S"),
                "tradeDirection": request.trade_direction, "ctptyName": request.short_name,
                "quotationOrderType": request.quotation_order_type,
                "dealNotional": 0, "dealPrice": 0,
            },
            "trdGoatsOptionStructure": {
                "contractType": request.contract_type, "direction": request.direction,
                "initialNotional": request.collateral_notional,
                "openPositionType": request.open_position_type,
                "initialUnderlyingPrice": request.initial_underlying_price_order,
                "algorithmOrderVol": request.algorithm_order_vol,
                "algorithmOrderStartTime": request.algorithm_order_start_time,
                "algorithmOrderEndTime": request.algorithm_order_end_time,
            },
        }
        self.owners[identifier] = (agent, user)
        self.applications[application_id] = identifier
        logger.info("模拟开仓下单成功：申请编号=%s，模拟订单=%s", application_id, identifier)
        return goats_response(application_id)

    def status(self, application_id: str, agent: str, user: str | None) -> dict[str, Any]:
        identifier = self.applications.get(application_id)
        if not self.visible(identifier, agent, user):
            return goats_response(error="模拟开仓申请不存在或不属于当前身份")
        return goats_response({"completed": True, "success": True, "failureMsg": None,
                               "keyStockOrderId": identifier})

    def query(self, request: OrderQuery, agent: str, user: str | None) -> dict[str, Any]:
        filters = (request.filter or OrderFilter()).model_dump(by_alias=True, exclude_none=True)
        rows = [row for identifier, row in self.orders.items()
                if self.visible(identifier, agent, user) and all(
                    not value or {
                        **row["trdGoatsOptionOrder"], **row["trdGoatsOptionStructure"],
                    }.get(key) == value for key, value in filters.items())]
        total = len(rows)
        if request.page_size:
            start = (request.page_num - 1) * request.page_size
            rows = rows[start:start + request.page_size]
        return goats_response({"pageNum": request.page_num, "pageSize": len(rows),
                               "total": total, "queryResults": deepcopy(rows)})

    def withdraw(self, identifier: int, agent: str, user: str | None) -> dict[str, Any]:
        if not self.visible(identifier, agent, user):
            return goats_response(error="模拟开仓订单不存在或不属于当前身份")
        code = f"MOCK-OPEN-CANCEL-{identifier}"
        if code not in self.withdrawals:
            self.withdrawals[code] = identifier
            self.orders[identifier]["trdGoatsOptionOrder"]["orderStatus"] = "PENDING_CANCEL"
            logger.info("模拟开仓撤单已受理：模拟订单=%s，撤单编号=%s", identifier, code)
        return goats_response({"completed": False, "stockOrderCode": code})

    def withdrawal_result(self, code: str, agent: str, user: str | None) -> dict[str, Any]:
        identifier = self.withdrawals.get(code)
        if identifier is None or not self.visible(identifier, agent, user):
            return goats_response(error="模拟开仓撤单回执不存在或不属于当前身份")
        self.orders[identifier]["trdGoatsOptionOrder"]["orderStatus"] = "CANCELLED"
        return goats_response({"completed": True, "stockOrderCode": code,
                               "withdrawResult": "SUCCESS", "failureMsg": None})


class MockSwap:
    """互换提交、审核和撤单；仅保存模拟状态，不创建成交或真实市场数据。"""

    def __init__(self) -> None:
        self.orders: dict[int, dict[str, Any]] = {}
        self.owners: dict[int, tuple[str, str | None]] = {}
        self.identifiers = count(1_200_000_000 + int(time.time()) % 100_000_000)

    def visible(self, identifier: int, agent: str, user: str | None) -> bool:
        owner = self.owners.get(identifier)
        return owner is not None and owner[0] == agent and (user is None or owner[1] == user)

    def place(self, request: SwapRequest, agent: str, user: str | None) -> dict[str, Any]:
        if (request.quantity is None) == (request.notional is None):
            return goats_response(error="模拟互换下单须提供唯一委托数量或金额")
        if request.price_type == "LimitOrder" and request.price is None and request.fix_price is None:
            return goats_response(error="限价单缺少价格")
        identifier = next(self.identifiers)
        now = datetime.now()
        self.orders[identifier] = {
            **request.model_dump(by_alias=True, exclude_none=True),
            "keyOrderId": identifier, "keyStockOrderId": identifier,
            "orderCode": f"MOCK-TRS-{identifier}",
            "orderDate": now.strftime("%Y-%m-%d"), "entrustDate": now.strftime("%Y-%m-%d"),
            "entrustTime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "ctptyShortName": request.short_name, "orderStatus": "NEW", "canWithdraw": True,
            "canReplace": False, "filledQty": 0, "avgPrice": 0, "execAmount": 0,
        }
        self.owners[identifier] = (agent, user)
        logger.info("模拟互换下单成功：模拟订单=%s", identifier)
        return goats_response({"keyOrderId": identifier, "result": True, "async": True,
                               "errMsg": None, "transactionType": request.transaction_type,
                               "orderCode": self.orders[identifier]["orderCode"]})

    def status(self, identifiers: list[int], agent: str, user: str | None) -> dict[str, Any]:
        if any(not self.visible(identifier, agent, user) for identifier in identifiers):
            return goats_response(error="模拟互换订单不存在或不属于当前身份")
        return goats_response([
            {"keyOrderId": identifier, "keyStockOrderId": identifier, "success": True,
             "completed": True, "failureMsg": None,
             "transactionType": self.orders[identifier]["transactionType"],
             "serialNo": str(identifier), "submitResultUuid": f"MOCK-TRS-{identifier}"}
            for identifier in identifiers
        ])

    def query(self, identifiers: list[int] | None, agent: str, user: str | None) -> dict[str, Any]:
        return goats_response([
            row for identifier, row in self.orders.items()
            if self.visible(identifier, agent, user)
            and (identifiers is None or identifier in identifiers)
        ])

    def withdraw(self, identifiers: list[int], agent: str, user: str | None) -> dict[str, Any]:
        if any(not self.visible(identifier, agent, user) for identifier in identifiers):
            return goats_response(error="模拟互换订单不存在或不属于当前身份")
        for identifier in identifiers:
            row = self.orders[identifier]
            row.update(orderStatus="CANCELED", canWithdraw=False, withdrawQty=row.get("quantity", 0))
        logger.info("模拟互换撤单成功：模拟订单=%s", identifiers)
        return goats_response([
            {"keyOrderId": identifier, "result": True, "msg": None} for identifier in identifiers
        ])


class MockTrading:
    """独立模拟订单；固定持仓不扣减，不模拟成交、额度或真实 GOATS 活跃单限制。"""

    def __init__(self, positions: list[dict[str, Any]]) -> None:
        self.positions = {row["contractCode"]: row for row in positions if row.get("contractCode")}
        self.orders: dict[int, dict[str, Any]] = {}
        self.owners: dict[int, tuple[str, str | None]] = {}
        self.withdrawals: dict[str, int] = {}
        self.identifiers = count(time.time_ns() // 1000)

    def visible(self, identifier: int, agent: str, user: str | None) -> bool:
        owner = self.owners.get(identifier)
        return owner is not None and owner[0] == agent and (user is None or owner[1] == user)

    def place(self, request: CloseRequest, agent: str, user: str | None) -> dict[str, Any]:
        position = self.positions.get(request.contract_code)
        if position is None:
            return goats_response(error=f"合约{request.contract_code}不存在于模拟持仓")
        if not position["allowCloseOut"] or position.get("hasCloseRecord") is True:
            return goats_response(error="模拟持仓当前不可平仓")
        available = Decimal(str(position.get("availableNotional", 0)))
        if request.notional_delta > available:
            return goats_response(error="平仓名义本金超过模拟持仓的可平仓本金")
        if request.algo_type == "LIMIT" and request.price is None:
            return goats_response(error="限价单缺少价格")
        if request.algo_type == "POV" and request.pov_ratio is None:
            return goats_response(error="POV 缺少跟量比例")
        if request.algo_type == "TWAP" and not (request.algo_start_time and request.algo_end_time):
            return goats_response(error="TWAP 缺少起止时间")
        identifier = next(self.identifiers)
        now = datetime.now()
        self.orders[identifier] = {
            "keyStockOrderId": identifier,
            "tradeDate": now.strftime("%Y-%m-%d"),
            "tradeTime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "keyContractInstId": position.get("keyInstrumentId"),
            "contractCode": request.contract_code,
            "underlyingInsId": position.get("underlyingInsId"),
            "windCode": position["windcode"], "windName": position.get("windname"),
            "tradeDirection": "SELL", "notionalDelta": request.notional_delta,
            "algoType": request.algo_type, "openPositionType": request.algo_type,
            "price": request.price, "povRatio": request.pov_ratio,
            "algoStartTime": request.algo_start_time, "algoEndTime": request.algo_end_time,
            "closeOutType": "FULL_TERMINATION" if request.notional_delta == available else "PARTIAL_TERMINATION",
            "contractType": position["contractType"], "contractSubType": position.get("contractSubType"),
            "keyCtptyId": position.get("keyCtptyId"),
            "stockOrderStatus": "OTC_VERIFYING", "allowWithdraw": True,
            "dealNotional": 0, "dealPrice": None, "clientExecutedPercentage": 0,
            "orderTakingTime": None, "orderCompletedTime": None,
            "goatsPositionQueryDto": deepcopy(position),
        }
        self.owners[identifier] = (agent, user)
        logger.info("模拟平仓下单成功：合约=%s，模拟订单=%s，名义本金=%s", request.contract_code, identifier, request.notional_delta)
        return goats_response({"keyStockOrderId": identifier})

    def query(self, request: OrderQuery, agent: str, user: str | None) -> dict[str, Any]:
        filters = (request.filter or OrderFilter()).model_dump(by_alias=True)
        rows = [
            row for identifier, row in self.orders.items()
            if self.visible(identifier, agent, user)
            and all(not value or row.get(key) == value for key, value in filters.items())
        ]
        total = len(rows)
        if request.page_size:
            start = (request.page_num - 1) * request.page_size
            rows = rows[start : start + request.page_size]
        return goats_response({"pageNum": request.page_num, "pageSize": len(rows), "total": total, "queryResults": deepcopy(rows)})

    def withdraw(self, identifier: int, agent: str, user: str | None) -> dict[str, Any]:
        if not self.visible(identifier, agent, user):
            return goats_response(error="模拟订单不存在")
        code = f"MOCK-CANCEL-{identifier}"
        self.withdrawals[code] = identifier
        self.orders[identifier].update(
            stockOrderStatus="CANCELED", allowWithdraw=False,
            orderCompletedTime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        logger.info("模拟撤单成功：模拟订单=%s，撤单编号=%s", identifier, code)
        return goats_response({"stockOrderCode": code})

    def withdrawal_result(self, code: str, agent: str, user: str | None) -> dict[str, Any]:
        identifier = self.withdrawals.get(code)
        if identifier is None or not self.visible(identifier, agent, user):
            return goats_response(error="模拟撤单记录不存在")
        return goats_response({"completed": True, "withdrawResult": "SUCCESS", "failureMsg": None})


def load_snapshot(path: Path) -> dict[str, Any]:
    """校验查询所需字段，原始响应及未知字段完整保留。"""
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"无法加载持仓数据 {path}: {exc}") from exc

    def invalid(reason: str) -> ValueError:
        return ValueError(f"持仓数据格式错误 {path}: {reason}")

    if not isinstance(snapshot, dict):
        raise invalid("根节点必须是 GOATS 响应对象")
    if "errMsg" not in snapshot or not isinstance(snapshot["errMsg"], str | None):
        raise invalid("errMsg 必须是字符串或 null")
    code = snapshot.get("errCode")
    if not isinstance(code, dict) or code.get("code") != 200:
        raise invalid("errCode.code 必须为 200")
    data = snapshot.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("queryResults"), list):
        raise invalid("data.queryResults 必须是持仓对象数组")
    for index, row in enumerate(data["queryResults"]):
        if not isinstance(row, dict):
            raise invalid(f"queryResults[{index}] 必须是对象")
        for field in ("windcode", "insFamily", "contractType"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise invalid(f"queryResults[{index}].{field} 必须是非空字符串")
        if not isinstance(row.get("allowCloseOut"), bool):
            raise invalid(f"queryResults[{index}].allowCloseOut 必须是布尔值")
        if not isinstance(row.get("contractSubType"), str | None):
            raise invalid(f"queryResults[{index}].contractSubType 必须是字符串或 null")
    return snapshot


def create_app(data_file: Path = DEFAULT_DATA_FILE) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.snapshot = load_snapshot(data_file)
        application.state.trading = MockTrading(application.state.snapshot["data"]["queryResults"])
        application.state.opening = MockOpening()
        application.state.swap = MockSwap()
        logger.info(
            "持仓数据加载完成：文件=%s，数量=%s 条",
            data_file,
            len(application.state.snapshot["data"]["queryResults"]),
        )
        logger.info("模拟交易已启用：开仓、平仓、订单查询、撤单及撤单结果；订单仅保存在内存，重启清空")
        yield

    application = FastAPI(title="GOATS 期权 Mock（持仓、开仓、平仓、撤单）", lifespan=lifespan)

    @application.post("/api/internal/agent/trs/order")
    async def place_swap(
        request: SwapRequest, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.swap.place(request, agentid, agentsubid)

    @application.post("/api/internal/agent/trs/order/status")
    async def swap_status(
        request: list[SwapStatusRequest], agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.swap.status([item.key_order_id for item in request], agentid, agentsubid)

    @application.post("/api/internal/agent/trs/order/query")
    async def query_swap(
        agentid: Annotated[str, Header(min_length=1)], request: SwapQuery | None = None,
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        identifiers = request.key_order_id_list if request else None
        return application.state.swap.query(identifiers, agentid, agentsubid)

    @application.post("/api/internal/agent/trs/order/withdraw")
    async def withdraw_swap(
        request: SwapWithdrawRequest, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.swap.withdraw(request.order_list, agentid, agentsubid)

    @application.post("/api/internal/agent/option/order")
    async def place_open(
        request: OpenRequest, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.opening.place(request, agentid, agentsubid)

    @application.get("/api/internal/agent/option/order/status")
    async def query_open_status(
        order_id: Annotated[str, Query(alias="orderId", min_length=1)],
        agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.opening.status(order_id, agentid, agentsubid)

    @application.post("/api/internal/agent/option/order/query")
    async def query_open(
        request: OrderQuery, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.opening.query(request, agentid, agentsubid)

    @application.post("/api/internal/agent/option/order/withdraw")
    async def withdraw_open(
        request: WithdrawRequest, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.opening.withdraw(request.key_stock_order_id, agentid, agentsubid)

    @application.get("/api/internal/agent/option/order/withdrawResult")
    async def query_open_withdrawal(
        stock_order_code: Annotated[str, Query(alias="stockOrderCode", min_length=1)],
        agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return application.state.opening.withdrawal_result(stock_order_code, agentid, agentsubid)

    @application.post("/api/internal/agent/option/order/close")
    async def place_close(
        request: CloseRequest, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        trading: MockTrading = application.state.trading
        return trading.place(request, agentid, agentsubid)

    @application.post("/api/internal/agent/option/order/close/query")
    async def query_close(
        request: OrderQuery, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        trading: MockTrading = application.state.trading
        return trading.query(request, agentid, agentsubid)

    @application.post("/api/internal/agent/option/order/close/withdraw")
    async def withdraw_close(
        request: WithdrawRequest, agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        trading: MockTrading = application.state.trading
        return trading.withdraw(request.key_stock_order_id, agentid, agentsubid)

    @application.get("/api/internal/agent/option/order/close/withdrawResult")
    async def query_withdrawal(
        stock_order_code: Annotated[str, Query(alias="stockOrderCode", min_length=1)],
        agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        trading: MockTrading = application.state.trading
        return trading.withdrawal_result(stock_order_code, agentid, agentsubid)

    @application.post("/api/internal/agent/option/position")
    async def query_positions(
        query: PositionQuery,
        agentid: Annotated[str, Header(min_length=1)],
        agentsubid: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        snapshot = application.state.snapshot
        filters = query.filter or PositionFilter()
        matches = [row for row in snapshot["data"]["queryResults"] if filters.matches(row)]
        total = len(matches)
        if query.page_size:
            start = (query.page_num - 1) * query.page_size
            matches = matches[start : start + query.page_size]
        response: dict[str, Any] = deepcopy(snapshot)
        response["data"].update(
            pageNum=query.page_num, pageSize=len(matches), total=total, queryResults=matches
        )
        return response

    return application


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 GOATS 期权 Mock 服务（持仓、开仓、平仓、撤单）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=20000, help="监听端口（默认 20000）")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1 到 65535 之间")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_config=logging_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
