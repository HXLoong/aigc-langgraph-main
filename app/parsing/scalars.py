"""保留模型候选的 JSON 标量类型，最终 Java 类型由清洗节点装配。"""
from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr

# 严格类型防止 true→1、数字→字符串等隐式转换先于审计发生。
CandidateScalar = StrictStr | StrictBool | StrictInt | StrictFloat
