"""Java 标的工具共用 blocking 信封；与企微主图的超时和 State 独立。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Literal

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from app.graph.state import ErrorInfo
from app.llm.budget import model_request_scope
from app.observability.logs import bound_request_context
from app.observability.tracing import HandledErrorCallback, attach_request_trace

logger = logging.getLogger(__name__)
TOOL_TIMEOUT_SECONDS = 60.0


class ToolRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    response_mode: str = Field(default="blocking", description="仅支持 blocking")
    user: str = Field(default="", description="调用方用户标识，用于追踪")


class ToolRunData(BaseModel):
    id: str = Field(description="本次运行标识")
    workflow_id: str = Field(description="工作流名称")
    status: Literal["succeeded", "failed"] = Field(description="图执行状态")
    outputs: dict[str, Any] = Field(description="成功输出；失败为空对象")
    error: str | None = Field(description="失败原因；成功为 null")
    elapsed_time: float = Field(description="端到端耗时，秒")
    total_tokens: int = Field(description="模型已报告的总 token 数")
    total_steps: int = Field(description="实际结束的图节点数")
    created_at: int = Field(description="开始时间，Unix 秒")
    finished_at: int = Field(description="结束时间，Unix 秒")
    model_requests: int = Field(description="真实模型 HTTP POST 尝试次数，含失败请求")
    usage: dict[str, int] = Field(description="已报告的 input_tokens/output_tokens/total_tokens")


class ToolResponse(BaseModel):
    workflow_run_id: str = Field(description="本次运行标识，去连字符后等于 X-Trace-Id")
    task_id: str = Field(description="本次任务标识，与运行标识相同")
    data: ToolRunData = Field(description="Dify blocking 运行结果")


class ToolUsageCallback(BaseCallbackHandler):
    """在解析前记录 usage；模型截断或结构化解析失败仍保留已计费用量。"""

    run_inline = True

    def __init__(self) -> None:
        self.usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self.trace_ids: set[str] = set()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if usage:
                    for key in self.usage:
                        self.usage[key] += int(usage.get(key, 0))

    def on_chain_end(self, outputs: Any, **kwargs: Any) -> None:
        # safe_node 自带单节点 trace；根图不能重复累计。
        if isinstance(outputs, dict) and isinstance(outputs.get("trace"), list):
            self.trace_ids.update(str(entry.id) for entry in outputs["trace"])


async def run_tool_workflow(
    graph: Runnable[Any, Any],
    state: dict[str, Any],
    *,
    workflow: str,
    request: ToolRequest,
    model_limit: int,
) -> JSONResponse:
    if request.response_mode != "blocking":
        raise HTTPException(status_code=400, detail="标的工具仅支持 blocking 模式")
    run_id = uuid.uuid4()
    trace_id = run_id.hex
    state["trace_id"] = trace_id
    started = time.time()
    clock = time.perf_counter()
    usage = ToolUsageCallback()
    final: dict[str, Any] = {}
    failure: str | None = None
    status_code = 200
    with (
        model_request_scope(limit=model_limit) as budget,
        bound_request_context(
            trace_id=trace_id,
            workflow_run_id=str(run_id),
        ),
    ):
        try:
            async with asyncio.timeout(TOOL_TIMEOUT_SECONDS):
                trace = await attach_request_trace(request_trace_id=trace_id, traceparent=None)
                callbacks: list[Any] = [usage]
                if trace.handler is not None:
                    callbacks.extend([HandledErrorCallback(trace.handler), trace.handler])
                config: RunnableConfig = {
                    "run_name": workflow,
                    "callbacks": callbacks,
                    "metadata": {
                        "trace_id": trace_id,
                        "workflow_run_id": str(run_id),
                        "langfuse_user_id": request.user,
                    },
                }
                final = await graph.ainvoke(state, config=config)
                error = final.get("error")
                if isinstance(error, ErrorInfo):
                    failure = f"{error.node}: {error.type}: {error.message}"
                elif error:
                    failure = str(error)
        except TimeoutError:
            status_code = 504
            failure = f"workflow_timeout: {workflow} 超过 {TOOL_TIMEOUT_SECONDS:g} 秒整体期限"
        except Exception as exc:
            logger.exception("instrument workflow execution failed")
            failure = f"{type(exc).__name__}: {exc}"
        if failure and status_code == 200:
            status_code = 500
        result = ToolResponse(
            workflow_run_id=str(run_id),
            task_id=str(run_id),
            data=ToolRunData(
                id=str(run_id),
                workflow_id=workflow,
                status="failed" if failure else "succeeded",
                outputs={} if failure else final.get("outputs", {}),
                error=failure,
                elapsed_time=round(time.perf_counter() - clock, 6),
                total_tokens=usage.usage["total_tokens"],
                total_steps=len(final["trace"]) if "trace" in final else len(usage.trace_ids),
                created_at=int(started),
                finished_at=int(time.time()),
                model_requests=budget.requests,
                usage=usage.usage,
            ),
        )
        logger.info(
            "instrument_workflow workflow=%s run_id=%s status=%s elapsed=%s requests=%s usage=%s error=%s",
            workflow,
            run_id,
            result.data.status,
            result.data.elapsed_time,
            budget.requests,
            usage.usage,
            failure,
        )
        return JSONResponse(
            status_code=status_code, content=result.model_dump(), headers={"X-Trace-Id": trace_id}
        )
