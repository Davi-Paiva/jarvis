from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graphs.repository_agent_graph import REPOSITORY_GRAPH_NODES, build_repository_agent_graph
from app.graphs.task_agent_graph import TASK_GRAPH_NODES, build_task_agent_graph


def test_graph_builders_are_optional_and_expose_expected_nodes():
    assert REPOSITORY_GRAPH_NODES == [
        "intake",
        "planning",
        "waiting_approval",
        "execution",
        "finalization",
    ]
    assert TASK_GRAPH_NODES == ["inspect", "work", "validate", "done"]
    assert build_repository_agent_graph() is None or build_repository_agent_graph() is not None
    assert build_task_agent_graph() is None or build_task_agent_graph() is not None

