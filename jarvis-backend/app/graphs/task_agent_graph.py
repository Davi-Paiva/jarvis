from __future__ import annotations

from typing import Any, Dict, Optional


try:
    from langgraph.graph import END, START, StateGraph  # type: ignore

    LANGGRAPH_AVAILABLE = True
except Exception:
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore
    LANGGRAPH_AVAILABLE = False


TASK_GRAPH_NODES = ["inspect", "work", "validate", "done"]


def build_task_agent_graph(checkpointer: Optional[Any] = None) -> Optional[Any]:
    if not LANGGRAPH_AVAILABLE or StateGraph is None:
        return None

    workflow = StateGraph(dict)
    workflow.add_node("inspect", _mark_node("inspect"))
    workflow.add_node("work", _mark_node("work"))
    workflow.add_node("validate", _mark_node("validate"))
    workflow.add_node("done", _mark_node("done"))
    workflow.add_edge(START, "inspect")
    workflow.add_edge("inspect", "work")
    workflow.add_edge("work", "validate")
    workflow.add_edge("validate", "done")
    workflow.add_edge("done", END)
    return workflow.compile(checkpointer=checkpointer)


def _mark_node(node_name: str):
    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        next_state = dict(state)
        next_state["graph_node"] = node_name
        return next_state

    return _node

