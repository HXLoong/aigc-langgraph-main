"""Dify error envelope at the workflow HTTP boundary."""
from fastapi import Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response


async def workflow_http_error(request: Request, exc: HTTPException) -> Response:
    if request.url.path != "/v1/workflows/run":
        return await http_exception_handler(request, exc)
    code = "internal_server_error" if exc.status_code >= 500 else "invalid_param"
    if exc.status_code == 401:
        code = "unauthorized"
    return JSONResponse(status_code=exc.status_code, content={
        "code": code, "message": str(exc.detail), "status": exc.status_code,
    }, headers=exc.headers)


async def workflow_validation_error(request: Request, exc: RequestValidationError) -> Response:
    if request.url.path != "/v1/workflows/run":
        return await request_validation_exception_handler(request, exc)
    # Validation input values can contain credentials or client messages.
    return JSONResponse(status_code=422, content={
        "code": "invalid_param", "message": "请求字段缺失或格式不正确。", "status": 422,
    })
