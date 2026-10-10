"""instrument-ranking blocking HTTP 入口。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.tool_workflows import ToolResponse, run_tool_workflow
from instrument_ranking.models import RankingRequest

router = APIRouter(prefix="/instrument-ranking", tags=["instrument-ranking"])


@router.post(
    "/v1/workflows/run",
    response_model=ToolResponse,
    responses={
        500: {"model": ToolResponse, "description": "工作流或模型执行失败"},
        504: {"model": ToolResponse, "description": "工作流整体超时"},
    },
)
async def run(body: RankingRequest, request: Request) -> JSONResponse:
    return await run_tool_workflow(
        request.app.state.instrument_ranking_graph,
        {
            "raw_list": body.inputs.list,
            "keyword": body.inputs.keyword,
            "predicted_family": body.inputs.predictedInsFamily,
            "expected_transaction_type": body.inputs.expectedTransactionType,
        },
        workflow="instrument-ranking",
        request=body,
        model_limit=1,
    )
