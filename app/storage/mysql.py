"""Fixed table ownership and connection settings for the shared MySQL database."""
from typing import Any
from urllib.parse import unquote, urlsplit

COLLATION = "utf8mb4_general_ci"
SESSION_INIT = f"SET NAMES utf8mb4 COLLATE {COLLATION}"
MESSAGE_LOG = "langgraph_message_log"
NODE_TRACE = "langgraph_node_trace"
SHADOW_COMPARE = "langgraph_shadow_compare"
ALEMBIC_VERSION = "langgraph_alembic_version"
CHECKPOINT_TABLES = ("langgraph_checkpoint_writes", "langgraph_checkpoint_blobs", "langgraph_checkpoints")


def connection_args(uri: str) -> dict[str, Any]:
    parsed = urlsplit(uri)
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("MySQL URI must select a database")
    return {"host": parsed.hostname or "localhost", "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""), "password": unquote(parsed.password or ""),
            "db": database, "charset": "utf8mb4", "init_command": SESSION_INIT}
