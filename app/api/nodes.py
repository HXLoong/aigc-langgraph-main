"""节点调试 API：准备 Langfuse State，或隔离执行单个注册节点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from app.node_execution.executor import MissingNodeContextError, NodeExecutor
from app.node_execution.prepare import prepare_state

router = APIRouter(prefix="/v1/nodes", tags=["nodes"])


class NodeRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product: str
    node: str
    state: dict[str, Any]


class NodePrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product: str
    node: str
    langfuse_input: dict[str, Any]


class NodePrepareConversion(BaseModel):
    field: str
    from_type: str
    to_type: str
    rule: str


class PreparedRunRequest(BaseModel):
    product: str
    node: str
    state: dict[str, Any]


class NodePrepareSuccess(BaseModel):
    request: PreparedRunRequest
    dropped_fields: list[str]
    conversions: list[NodePrepareConversion]


class NodePrepareFailure(NodePrepareSuccess):
    missing_fields: list[str]
    detail: list[dict[str, Any]]


_PREPARE_EXAMPLES = {
    "normal_pruning": {
        "summary": "裁剪节点不会读取的字段",
        "value": {
            "product": "option_close",
            "node": "close_intent",
            "langfuse_input": {
                "raw_text": "我要平仓",
                "quote_content": "",
                "history_messages": [],
                "message_id": "123",
                "trace": [],
                "field_records": {},
            },
        },
    },
    "safe_conversion": {
        "summary": "安全转换后端上下文",
        "value": {
            "product": "option",
            "node": "option_extract_query",
            "langfuse_input": {
                "raw_text": "查询订单 Q-20260921-1234567890",
                "quote_content": "",
                "conversation_id": "conv-1",
                "message_id": "123",
                "room_id": "room-1",
                "user_id": "user-1",
            },
        },
    },
    "missing_context": {
        "summary": "一次返回全部缺失后端上下文",
        "value": {
            "product": "option",
            "node": "option_extract_query",
            "langfuse_input": {"raw_text": "查询订单"},
        },
    },
}

_PREPARE_SUCCESS_EXAMPLES = {
    "normal_pruning": {
        "summary": "裁剪成功",
        "value": {
            "request": {
                "product": "option_close",
                "node": "close_intent",
                "state": {
                    "raw_text": "我要平仓",
                    "quote_content": "",
                    "history_messages": [],
                },
            },
            "dropped_fields": ["message_id", "trace", "field_records"],
            "conversions": [],
        },
    },
    "safe_conversion": {
        "summary": "安全转换成功",
        "value": {
            "request": {
                "product": "option",
                "node": "option_extract_query",
                "state": {
                    "raw_text": "查询订单 Q-20260921-1234567890",
                    "quote_content": "",
                    "conversation_id": "conv-1",
                    "message_id": 123,
                    "room_id": "room-1",
                    "user_id": "user-1",
                },
            },
            "dropped_fields": [],
            "conversions": [
                {
                    "field": "message_id",
                    "from_type": "string",
                    "to_type": "integer",
                    "rule": "integer_string",
                }
            ],
        },
    },
}

_PREPARE_FAILURE_EXAMPLES = {
    "missing_context": {
        "summary": "缺少必需后端上下文",
        "value": {
            "request": {
                "product": "option",
                "node": "option_extract_query",
                "state": {"raw_text": "查询订单"},
            },
            "dropped_fields": [],
            "conversions": [],
            "missing_fields": [
                "conversation_id",
                "room_id",
                "user_id",
                "message_id",
            ],
            "detail": [
                {
                    "loc": ["state", field],
                    "type": "missing",
                    "msg": "Required node context is missing or empty",
                }
                for field in (
                    "conversation_id",
                    "room_id",
                    "user_id",
                    "message_id",
                )
            ],
        },
    }
}


@router.post(
    "/prepare",
    response_model=NodePrepareSuccess,
    responses={
        200: {
            "content": {
                "application/json": {"examples": _PREPARE_SUCCESS_EXAMPLES}
            }
        },
        422: {
            "model": NodePrepareFailure,
            "content": {
                "application/json": {"examples": _PREPARE_FAILURE_EXAMPLES}
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "content": {"application/json": {"examples": _PREPARE_EXAMPLES}}
        }
    },
)
async def prepare_node(body: NodePrepareRequest, request: Request) -> JSONResponse:
    executor: NodeExecutor = request.app.state.node_executor
    identity = {"product": body.product, "node": body.node}
    registration = executor.registrations.get((body.product, body.node))
    if registration is None:
        return JSONResponse(status_code=404, content={**identity, "detail": "Node not registered"})

    result = prepare_state(registration, body.langfuse_input)
    content: dict[str, Any] = {
        "request": {**identity, "state": result.state},
        "dropped_fields": result.dropped_fields,
        "conversions": result.conversions,
    }
    if not result.valid:
        content.update(
            missing_fields=result.missing_fields,
            detail=result.detail,
        )
        return JSONResponse(status_code=422, content=content)
    return JSONResponse(status_code=200, content=content)


@router.post("/run")
async def run_node(body: NodeRunRequest, request: Request) -> JSONResponse:
    executor: NodeExecutor = request.app.state.node_executor
    identity = {"product": body.product, "node": body.node}
    if (body.product, body.node) not in executor.registrations:
        return JSONResponse(status_code=404, content={**identity, "detail": "Node not registered"})
    try:
        state = executor.validate(body.product, body.node, body.state)
    except ValidationError as exc:
        return JSONResponse(
            status_code=422,
            content={
                **identity,
                "detail": exc.errors(include_url=False, include_context=False, include_input=False),
            },
        )
    except MissingNodeContextError as exc:
        return JSONResponse(
            status_code=422,
            content={
                **identity,
                "detail": [
                    {
                        "loc": ["state", field],
                        "type": "missing",
                        "msg": "Required node context is missing or empty",
                    }
                    for field in exc.fields
                ],
            },
        )
    try:
        output = await executor.run(body.product, body.node, state)
    except Exception as exc:  # noqa: BLE001 - HTTP 执行边界，ticker 异常按原策略穿透至此
        return JSONResponse(
            status_code=500,
            content={
                **identity,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            },
        )
    return JSONResponse(
        status_code=500 if output.get("error") else 200, content={**identity, "output": output}
    )
