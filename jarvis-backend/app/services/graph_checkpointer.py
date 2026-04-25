from __future__ import annotations

from typing import Any, Optional


def create_langgraph_sqlite_checkpointer(db_path: str) -> Optional[Any]:
    """Create LangGraph's SQLite checkpointer when the package is installed."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore

        return SqliteSaver.from_conn_string(db_path)
    except Exception:
        return None

