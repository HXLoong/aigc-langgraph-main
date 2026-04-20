"""历史消息加载模块。

对应 Dify 的 `处理历史输入` 节点 + `互换历史输入追加` + `历史输入追加` 节点。

核心思路：
1. LangGraph 的 checkpointer 按 thread_id (= conversation_id) 自动保存每一步 state
2. 每次新消息进入时，通过 `graph.aget_state(config)` 取回上一次的 state
3. 从 state['wechat_input'] + state['api_result'] 重建对话历史
4. 拼装成 `history_messages` 写入当前 state，供 LLM 节点使用

与 Dify 的对比：
- Dify 用 assigner 节点手工维护 history_query_str，容易丢/乱序
- LangGraph 天然用 checkpoint 存状态，这里只是"重整理"给 LLM 更易读的格式
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def load_history_from_checkpoint(
    graph: Any,
    conversation_id: str,
    max_turns: int = 10,
) -> list[dict]:
    """从 checkpoint 读取最近若干轮对话历史。

    Args:
        graph: 编译后的 graph（需提供 aget_state_history 方法）
        conversation_id: 作为 thread_id
        max_turns: 最多回溯几轮

    Returns:
        list of {role, content} dicts，时间顺序由旧到新
    """
    config = {"configurable": {"thread_id": conversation_id}}

    try:
        # LangGraph 提供 aget_state_history 可以回溯所有 checkpoint
        history_items = []
        count = 0
        async for snapshot in graph.aget_state_history(config):
            if count >= max_turns * 2:   # 每轮两条（用户+机器人）
                break
            history_items.append(snapshot)
            count += 1
    except Exception as e:
        logger.warning("读取 checkpoint 历史失败: %s", e)
        return []

    # 按时间顺序（由旧到新）反转
    history_items.reverse()

    messages: list[dict] = []
    for snapshot in history_items:
        values = snapshot.values if hasattr(snapshot, "values") else {}
        wx = values.get("wechat_input") or {}
        raw = wx.get("raw_content", "")
        api_result = values.get("api_result")

        if raw:
            messages.append({
                "role": "user",
                "content": raw,
                "message_id": wx.get("message_id"),
            })
        if api_result:
            messages.append({
                "role": "assistant",
                "content": str(api_result)[:1000],  # 截断防止过长
                "product_type": values.get("product_type"),
                "intent": values.get("intent"),
            })

    return messages


def format_history_for_prompt(messages: list[dict], max_chars: int = 4000) -> str:
    """把 history_messages 格式化为 LLM prompt 可用的字符串。

    对应 Dify 的 `history_query_str` 变量。
    """
    lines = []
    total = 0
    for msg in messages[-20:]:  # 最多 20 条
        role = msg.get("role", "?")
        content = msg.get("content", "")[:500]
        line = f"[{role}] {content}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines) if lines else "(无历史)"
