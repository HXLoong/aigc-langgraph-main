"""排序 HTTP 契约与模型输出契约。"""

from pydantic import BaseModel, ConfigDict, Field

from app.api.tool_workflows import ToolRequest


class RankingInputs(BaseModel):
    model_config = ConfigDict(strict=True)
    list: str = Field(description="候选标的 JSON 列表字符串，每项必须包含 windCode")
    keyword: str = Field(description="用户的完整查询原文")
    predictedInsFamily: str = Field(default="", description="模型预测的标的类型，仅作排序信号")  # noqa: N815
    expectedTransactionType: str = Field(default="", description="用户明确的交易品种，仅作排序信号")  # noqa: N815


class RankingRequest(ToolRequest):
    inputs: RankingInputs = Field(description="排序工作流输入")


class RankedCodes(BaseModel):
    result: list[str] = Field(
        description=(
            "仅返回候选中与完整查询意图相关的 windCode，按相关性从高到低排序且不重复；"
            "不得输出候选之外的代码。没有相关标的时返回空数组。"
        )
    )
