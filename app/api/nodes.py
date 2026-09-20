"""POST /v1/nodes/run：请求 State 与会话工作流完全隔离。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from app.node_execution.executor import MissingNodeContextError, NodeExecutor

router = APIRouter(prefix="/v1/nodes", tags=["nodes"])


class NodeRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product: str
    node: str
    state: dict[str, Any]


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
