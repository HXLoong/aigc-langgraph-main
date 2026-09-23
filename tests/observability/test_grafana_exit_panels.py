"""The rollout view must measure HTTP requests, not the number of graph nodes."""
import json
from pathlib import Path

from app.observability.metrics import METRIC_HTTP_RESPONSE_TOTAL


def test_rollout_panels_have_http_and_cascade_with_http_denominators():
    dashboard = json.loads(Path("infra/grafana/dashboards/otc-agent-overview.json").read_text())
    panels = dashboard["panels"]
    for window in ("5m", "7d"):
        for title in ("HTTP 5xx", "Cascade fail"):
            panel = next(p for p in panels if title in p["title"] and window in p["title"])
            query = panel["targets"][0]["expr"]
            assert METRIC_HTTP_RESPONSE_TOTAL in query.split("/")[-1]
            assert "otc_agent_node_total" not in query
            assert f"[{window}]" in query
            steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
            assert steps[-1]["value"] == (0.001 if title == "HTTP 5xx" else 0.01)


def test_end_to_end_p95_excludes_node_histograms_and_keeps_node_panel():
    dashboard = json.loads(Path("infra/grafana/dashboards/otc-agent-overview.json").read_text())
    for window in ("5m", "7d"):
        panel = next(p for p in dashboard["panels"]
                     if "端到端 P95" in p["title"] and window in p["title"])
        query = panel["targets"][0]["expr"]
        assert 'node=""' in query and "histogram_quantile(0.95" in query
        assert "sum by (le)" in query and f"[{window}]" in query
    node_panel = next(p for p in dashboard["panels"] if p.get("id") == 102)
    assert "节点" in node_panel["title"]
    assert 'node!=""' in node_panel["targets"][0]["expr"]
