"""推断 HTTP 契约与三份模型输出契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.tool_workflows import ToolRequest


class InferenceInputs(BaseModel):
    model_config = ConfigDict(strict=True)
    list: str = Field(description="JSON 字符串，内容为标的原始表达列表")
    transactionTypes: str = Field(default="[]", description="可选交易品种范围的 JSON 列表字符串")  # noqa: N815
    inferencePrompt: str = Field(default="", description="Java 提供的附加推断规则")  # noqa: N815


class InferenceRequest(ToolRequest):
    inputs: InferenceInputs = Field(description="推断工作流输入")


class CodeInference(BaseModel):
    analysis: dict[str, str] = Field(
        description="各输入的简短判断依据；仅纠错、主力回落、多候选消歧或超范围时用一句话说明，否则为空字符串，不展开推理"
    )
    result: dict[str, list[str]] = Field(
        description=(
            "每个原始输入原文映射到去重字符串数组，必须覆盖全部输入；最多5项。"
            "代码在前、规范简称在后，不能直接以输入别名充当规范简称。"
            "无法推断或超出指定交易品种范围时为空数组。"
            "期货首位为具体可交易到期合约，按到期由近到远排序，不含主力、连续等合成代码；"
            "期货末尾追加品种中文名加两位年份的兜底词（如沪铜26）；非期货不追加。"
            "未指定管理人的ETF品类只放最多5个主流候选代码，按规模/流动性降序，不交错名称。"
        )
    )


class LiteralKeywords(BaseModel):
    result: dict[str, list[str]] = Field(
        description=(
            "每个原始输入原文映射到字面关键词字符串数组，必须覆盖全部输入；"
            "数组不定长，遵循分词规则次序，不推断、不补全代码或名称；无有效内容为空数组。"
        )
    )


class InstrumentFamilies(BaseModel):
    result: dict[str, Literal["EQUITY", "FUND", "FUTURE", "INDEX", ""]] = Field(
        description="每个原始输入原文映射到标的类型，必须覆盖全部输入；不能高置信判断时为空字符串"
    )
