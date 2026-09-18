"""Add complete HTTP response snapshots without deleting historical message records."""
from alembic import context, op
from sqlalchemy import Column, SmallInteger, inspect, text
from sqlalchemy.dialects.mysql import JSON, MEDIUMTEXT

from app.storage.mysql import MESSAGE_LOG

revision = "0001_request_replay"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set() if context.is_offline_mode() else {
        column["name"] for column in inspect(op.get_bind()).get_columns(MESSAGE_LOG)
    }
    for column in (
        Column("reply_text", MEDIUMTEXT(), nullable=True),
        Column("response_json", JSON(), nullable=True),
        Column("http_status", SmallInteger(), nullable=False, server_default=text("200")),
    ):
        if column.name not in existing:
            op.add_column(MESSAGE_LOG, column)


def downgrade() -> None:
    raise RuntimeError("Response snapshots are audit data; rolling back code must preserve them.")
