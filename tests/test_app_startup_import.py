"""The ASGI app must start after a branch changes its graph modules."""

from __future__ import annotations

import os
import subprocess
import sys


def test_asgi_app_starts_with_current_graph_modules() -> None:
    env = os.environ.copy()
    env["MYSQL_URI"] = "mysql+aiomysql://test:test@127.0.0.1:1/test"
    env["USE_MYSQL_CHECKPOINTER"] = "false"
    env["REQUEST_IDEMPOTENCY"] = "false"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient\n"
            "from app.main import app\n"
            "with TestClient(app) as client:\n"
            "    assert client.get('/health').status_code == 200\n",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
