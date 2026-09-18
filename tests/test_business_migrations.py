"""Business schema migrations can be reviewed offline before local application."""
import subprocess
import sys
from pathlib import Path


def test_replay_migration_emits_additive_reviewable_sql():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head", "--sql"],
        cwd=root, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ADD COLUMN reply_text" in result.stdout
    assert "ADD COLUMN response_json" in result.stdout
    assert "ADD COLUMN http_status" in result.stdout
    assert "DROP " not in result.stdout


def test_migration_owns_only_prefixed_tables():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"], cwd=root, text=True, capture_output=True, check=True)
    assert "ALTER TABLE langgraph_message_log" in result.stdout
    assert "CREATE TABLE langgraph_alembic_version" in result.stdout
    assert "ALTER TABLE message_log" not in result.stdout
