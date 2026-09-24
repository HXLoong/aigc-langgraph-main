"""Langfuse 同步在 main 收到对应文件 push 时自动触发，也可手动重跑（Actions → Run workflow）。"""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("filename", ["langfuse-prompt-sync.yml", "langfuse-dataset-sync.yml"])
def test_sync_workflows_auto_trigger_on_main_push(filename: str) -> None:
    path = Path(".github/workflows") / filename
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    trigger = workflow["on"]

    assert set(trigger) == {"workflow_dispatch", "push"}
    assert trigger["push"]["branches"] == ["main"]
    assert trigger["push"]["paths"]
    assert "if" not in workflow["jobs"]["sync"]


def test_prompt_sync_workflow_trigger_and_runtime() -> None:
    path = Path(".github/workflows/langfuse-prompt-sync.yml")
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert set(workflow["on"]) == {"workflow_dispatch", "push"}
    assert workflow["on"]["push"]["paths"] == [
        "app/prompts/option/*.md",
        "app/prompts/option_close/*.md",
        "app/prompts/swap/*.md",
    ]

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
