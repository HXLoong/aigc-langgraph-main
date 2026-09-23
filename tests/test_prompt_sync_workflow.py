"""提示词同步只在相关 PR 合入 main 后自动运行。"""

from pathlib import Path

import yaml


def test_prompt_sync_workflow_trigger_and_runtime() -> None:
    path = Path(".github/workflows/langfuse-prompt-sync.yml")
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    trigger = workflow["on"]
    assert "workflow_dispatch" in trigger
    pr = trigger["pull_request"]
    assert pr["types"] == ["closed"]
    assert pr["branches"] == ["main"]
    assert {
        "app/prompts/option/*.md",
        "app/prompts/option_close/*.md",
        "app/prompts/swap/*.md",
        "scripts/langfuse/upload_prompt_to_langfuse.py",
    } <= set(pr["paths"])

    job = workflow["jobs"]["sync"]
    assert "github.event.pull_request.merged == true" in job["if"]
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
