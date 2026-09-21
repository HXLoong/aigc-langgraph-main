"""Java 重投通知契约；原始业务回执与幂等快照保持完整。"""
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def project_retry_notification(response: dict[str, Any], inputs: Mapping[str, Any]) -> dict[str, Any]:
    """只有系统重投的重复通知静默；普通业务拒绝及原始结果照常保留。"""
    data = response.get("data")
    outputs = data.get("outputs") if isinstance(data, dict) else None
    if (str(inputs.get("retry_origin") or "").strip() != "XBOT_GET_DIFY_FAIL"
            or str(inputs.get("fast_query") or "") == "1"
            or not isinstance(outputs, dict) or outputs.get("api_code") != 900):
        return response
    projected = deepcopy(response)
    projected["answer"] = "IGNORE_REQUEST_NOT_REPLY_USER"
    projected["data"]["outputs"]["reply_text"] = projected["answer"]
    projected["metadata"] = {**(projected.get("metadata") or {}),
                             "notification_suppressed": True,
                             "reason": "system_retry_duplicate"}
    return projected
