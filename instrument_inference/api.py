"""instrument-inference blocking HTTP 入口。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.tool_workflows import ToolResponse, run_tool_workflow
from instrument_inference.models import InferenceRequest

router = APIRouter(prefix="/instrument-inference", tags=["instrument-inference"])


@router.post(
    "/v1/workflows/run",
    response_model=ToolResponse,
    responses={
        500: {"model": ToolResponse, "description": "工作流或模型执行失败"},
        504: {"model": ToolResponse, "description": "工作流整体超时"},
    },
)
async def run(body: InferenceRequest, request: Request) -> JSONResponse:
    return await run_tool_workflow(
        request.app.state.instrument_inference_graph,
        {
            "raw_list": body.inputs.list,
            "transaction_types": body.inputs.transactionTypes,
            "inference_prompt": body.inputs.inferencePrompt,
        },
        workflow="instrument-inference",
        request=body,
        model_limit=3,
    )
