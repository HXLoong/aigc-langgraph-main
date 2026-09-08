from __future__ import annotations

import pytest

from app.graph.state import Message
from app.nodes.record_history import record_history


@pytest.mark.asyncio
async def test_record_history_appends_current_user_and_assistant_messages() -> None:
    update = await record_history(
        {
            "raw_text": "100万",
            "reply_text": "已补充名义本金100万元。",
        }
    )

    assert update == {
        "history_messages": [
            Message(role="user", content="100万"),
            Message(role="assistant", content="已补充名义本金100万元。"),
        ]
    }
