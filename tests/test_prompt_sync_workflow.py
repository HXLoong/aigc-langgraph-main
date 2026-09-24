"""Langfuse 同步只手动触发（Actions → Run workflow），不随 push / PR 自动写远端。"""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("filename", ["langfuse-prompt-sync.yml", "langfuse-dataset-sync.yml"])
def test_sync_workflows_are_manual_only(filename: str) -> None:
    path = Path(".github/workflows") / filename
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    trigger = workflow["on"]

    assert set(trigger) == {"workflow_dispatch"}
    assert "if" not in workflow["jobs"]["sync"]


def test_prompt_sync_workflow_trigger_and_runtime() -> None:
    path = Path(".github/workflows/langfuse-prompt-sync.yml")
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert set(workflow["on"]) == {"workflow_dispatch"}

    job = workflow["jobs"]["sync"]
    assert "if" not in job
    assert job["env"] == {
        "LANGFUSE_BASE_URL": "${{ vars.LANGFUSE_BASE_URL }}",
        "LANGFUSE_PUBLIC_KEY": "${{ secrets.LANGFUSE_PUBLIC_KEY }}",
        "LANGFUSE_SECRET_KEY": "${{ secrets.LANGFUSE_SECRET_KEY }}",
    }
    steps = job["steps"]
    assert (
        next(step for step in steps if step.get("uses", "").startswith("actions/checkout"))["with"][
            "ref"
        ]
        == "main"
    )
    assert any("langfuse==4.15.0" in step.get("run", "") for step in steps)
    assert any("--sync-all" in step.get("run", "") for step in steps)
    assert any(
        "LANGFUSE_BASE_URL LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY" in step.get("run", "")
        for step in steps
    )
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
