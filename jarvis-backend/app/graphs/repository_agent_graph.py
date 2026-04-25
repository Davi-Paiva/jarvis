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


REPOSITORY_GRAPH_NODES = [
    "intake",
    "planning",
    "waiting_approval",
    "execution",
    "finalization",
]


def build_repository_agent_graph(checkpointer: Optional[Any] = None) -> Optional[Any]:
    """Build a minimal LangGraph shape for repository agent state transitions.

    The orchestration logic lives in RepositoryAgent so it remains easy to call
    from tests and future endpoints. When LangGraph is installed, this compiled
    graph documents and validates the intended state machine shape.
    """
    if not LANGGRAPH_AVAILABLE or StateGraph is None:
        return None

    workflow = StateGraph(dict)
    workflow.add_node("intake", _mark_node("intake"))
    workflow.add_node("planning", _mark_node("planning"))
    workflow.add_node("waiting_approval", _mark_node("waiting_approval"))
    workflow.add_node("execution", _mark_node("execution"))
    workflow.add_node("finalization", _mark_node("finalization"))
    workflow.add_edge(START, "intake")
    workflow.add_edge("intake", "planning")
    workflow.add_edge("planning", "waiting_approval")
    workflow.add_edge("waiting_approval", "execution")
    workflow.add_edge("execution", "finalization")
    workflow.add_edge("finalization", END)
    return workflow.compile(checkpointer=checkpointer)


def _mark_node(node_name: str):
    def _node(state: Dict[str, Any]) -> Dict[str, Any]:
        next_state = dict(state)
        next_state["graph_node"] = node_name
        return next_state

    return _node

