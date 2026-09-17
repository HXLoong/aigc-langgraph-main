"""ticker structured output 契约（ADR 0022 未决项）：模型校验 + function calling 可转换性。

节点单测 mock 掉了 langchain 的 schema 转换环节，这里对 4 个契约模型做
`convert_to_openai_tool` 固定（DeepSeek structured output 经 function_calling 适配，ADR 0020）。
"""
from __future__ import annotations

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from app.subgraphs.ticker.models import (
    InferCodeOutput,
    JudgeTypeOutput,
    RankOutput,
    SplitKeywordsOutput,
)


class TestTickerOutputModels:
    def test_dict_models_validate_dynamic_mappings(self):
        """数据装在命名字段 results 下（schema-echo 根修的锚点形态）。"""
        assert InferCodeOutput.model_validate(
            {"results": {"贵州茅台": ["600519.SH"]}}
        ).results == {"贵州茅台": ["600519.SH"]}
        assert SplitKeywordsOutput.model_validate(
            {"results": {"02513智谱": ["02513"]}}
        ).results == {"02513智谱": ["02513"]}
        assert JudgeTypeOutput.model_validate(
            {"results": {"贵州茅台": "EQUITY"}}
        ).results == {"贵州茅台": "EQUITY"}

    def test_dict_models_reject_wrong_value_types(self):
        with pytest.raises(ValidationError):
            InferCodeOutput.model_validate({"results": {"贵州茅台": "600519.SH"}})
        with pytest.raises(ValidationError):
            SplitKeywordsOutput.model_validate({"results": {"02513智谱": [1, 2]}})

    def test_dict_models_require_results_anchor(self):
        """裸 object（旧 RootModel 形态）缺 results 锚点必须校验失败。"""
        with pytest.raises(ValidationError):
            InferCodeOutput.model_validate({"贵州茅台": ["600519.SH"]})

    def test_rank_output_is_plain_model(self):
        assert RankOutput(ranked_codes=["600519.SH"]).ranked_codes == ["600519.SH"]
        assert RankOutput(ranked_codes=[]).ranked_codes == []

    def test_models_convert_to_function_calling_tools(self):
        """4 个模型都必须能作为 function calling 参数 schema 转换（structured output 前置）。"""
        for model in (InferCodeOutput, SplitKeywordsOutput, JudgeTypeOutput, RankOutput):
            tool = convert_to_openai_tool(model)
            assert tool["type"] == "function"
            parameters = tool["function"]["parameters"]
            assert parameters["type"] == "object"

    def test_dict_models_expose_named_results_property(self):
        """schema-echo 根修锁：工具 schema 必须带 properties.results 锚点（禁止裸 object）。"""
        for model in (InferCodeOutput, SplitKeywordsOutput, JudgeTypeOutput):
            tool = convert_to_openai_tool(model)
            parameters = tool["function"]["parameters"]
            assert "results" in parameters["properties"]
            assert parameters["properties"]["results"]["type"] == "object"
