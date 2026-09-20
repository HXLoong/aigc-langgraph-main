"""只收集外层目标节点 updates；不从最终 State 或差值推算输出。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi.encoders import jsonable_encoder
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.types import Overwrite
from pydantic import BaseModel

from app.graph.retry import add_io_node
from app.node_execution.registry import NodeRegistration
from app.node_execution.validation import state_adapter
from app.tools.bot_context import BotContext


class MissingNodeContextError(ValueError):
    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        super().__init__("Missing required context: " + ", ".join(fields))


def serialize_update(value: Any) -> Any:
    if isinstance(value, Overwrite):
        return serialize_update(value.value)
    if isinstance(value, BaseModel):
        return serialize_update(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, dict):
        return {key: serialize_update(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_update(item) for item in value]
    return jsonable_encoder(value)


class NodeExecutor:
    def __init__(self, registrations: Sequence[NodeRegistration]) -> None:
        self.registrations = {(r.product, r.name): r for r in registrations}
        if len(self.registrations) != len(registrations):
            raise ValueError("Duplicate node registration")
        self.graphs = {}
        for key, spec in self.registrations.items():
            state_adapter(spec.input_schema)
            graph: StateGraph[Any, Any, Any, Any] = StateGraph(spec.state_schema)
            action = spec.action() if spec.factory else spec.action
            if spec.io:
                add_io_node(graph, spec.name, action, with_error_handler=spec.with_error_handler)
            else:
                # RunnableLambda 避免装饰器推断错输入 schema（与主图现有用法一致）。
                graph.add_node(spec.name, action if spec.factory else RunnableLambda(action))
            graph.add_edge(START, spec.name)
            graph.add_edge(spec.name, END)
            self.graphs[key] = graph.compile(checkpointer=False)

    def validate(self, product: str, node: str, state: dict[str, Any]) -> dict[str, Any]:
        spec = self.registrations[(product, node)]
        validated: dict[str, Any] = state_adapter(spec.input_schema).validate_python(state)
        missing = [field for field in spec.required if field not in validated]
        if spec.backend_context:
            missing.extend(BotContext.from_state(validated).missing_required())
        if missing:
            raise MissingNodeContextError(missing)
        return validated

    async def run(self, product: str, node: str, state: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        graph = self.graphs[(product, node)]
        handler = graph.builder.nodes[node].error_handler_node
        async for event in graph.astream(state, stream_mode="updates"):
            for name, update in event.items():
                if name in (node, handler) and update is not None:
                    output = serialize_update(update)
        return output
