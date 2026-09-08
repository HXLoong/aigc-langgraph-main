"""20. 大模型rerank(Dify)  POST /v1/workflows/run"""
from __future__ import annotations

import requests
from _utils import DIFY_API_KEY, DIFY_BASE_URL, report

print("20. 大模型rerank(Dify)  POST /v1/workflows/run")

try:
    r = requests.post(f"{DIFY_BASE_URL}/v1/workflows/run",
                      json={
                          "inputs": {
                              "list": '[{"windCode":"0200.HK","insShtDesc":"新濠国际发展"}]',
                              "keyword": "0200.hk",
                          },
                          "user": "ai-trading-assistant",
                          "response_mode": "blocking",
                      },
                      headers={
                          "Content-Type": "application/json",
                          "Authorization": f"Bearer {DIFY_API_KEY}",
                      },
                      timeout=15)
    d = r.json()
    if r.status_code == 200:
        report("大模型rerank(Dify)", True, 200, f"task_id={d.get('task_id','')}")
    else:
        msg = d.get("message", "") if isinstance(d, dict) else str(d)[:80]
        report("大模型rerank(Dify)", False, r.status_code, msg)
except requests.exceptions.ConnectionError:
    report("大模型rerank(Dify)", False, 0, "Dify 不在当前网络可达")
except Exception as e:
    report("大模型rerank(Dify)", False, 0, str(e)[:80])
