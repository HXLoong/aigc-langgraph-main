"""Langfuse 同步在 main 更新后运行，支持手动触发。"""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(
    ("filename", "expected_paths"),
    [
        (
            "langfuse-prompt-sync.yml",
            {
                "app/prompts/option/*.md",
                "app/prompts/option_close/*.md",
                "app/prompts/swap/*.md",
                "scripts/langfuse/upload_prompt_to_langfuse.py",
            },
        ),
        (
            "langfuse-dataset-sync.yml",
            {
                "tests/fixtures/intent/*.jsonl",
                "tests/fixtures/categories/*.jsonl",
                "scripts/langfuse/upload_golden_to_langfuse.py",
            },
        ),
    ],
)
def test_sync_workflows_run_after_main_push(
    filename: str, expected_paths: set[str]
) -> None:
    path = Path(".github/workflows") / filename
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    trigger = workflow["on"]

    assert "workflow_dispatch" in trigger
    assert "pull_request" not in trigger
    assert trigger["push"]["branches"] == ["main"]
    assert expected_paths <= set(trigger["push"]["paths"])
    assert "if" not in workflow["jobs"]["sync"]


def test_prompt_sync_workflow_trigger_and_runtime() -> None:
    path = Path(".github/workflows/langfuse-prompt-sync.yml")
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    trigger = workflow["on"]
    assert "workflow_dispatch" in trigger
    push = trigger["push"]
    assert push["branches"] == ["main"]
    assert {
        "app/prompts/option/*.md",
        "app/prompts/option_close/*.md",
        "app/prompts/swap/*.md",
        "scripts/langfuse/upload_prompt_to_langfuse.py",
    } <= set(push["paths"])

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
