#!/usr/bin/env python3
"""独立运行的 GOATS 期权持仓查询 mock，不连接业务服务或数据库。"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import copy, deepcopy
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, Header
from pydantic import BaseModel, Field, field_validator

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
                "fmt": "[%(levelname)s] 期权持仓 Mock 服务 | %(message)s",
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
        logger.info(
            "持仓数据加载完成：文件=%s，数量=%s 条",
            data_file,
            len(application.state.snapshot["data"]["queryResults"]),
        )
        yield

    application = FastAPI(title="GOATS 期权持仓 Mock", lifespan=lifespan)

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
    parser = argparse.ArgumentParser(description="启动 GOATS 期权持仓 mock")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=20000, help="监听端口（默认 20000）")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1 到 65535 之间")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_config=logging_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
