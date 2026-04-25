from __future__ import annotations

import sqlite3
from typing import Any, Optional


def create_langgraph_sqlite_checkpointer(db_path: str) -> Optional[Any]:
    """Create LangGraph's SQLite checkpointer when the package is installed."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore

        # Create a persistent connection and pass it to SqliteSaver
        # SqliteSaver.from_conn_string returns a context manager, so we need to create
        # the connection directly to avoid the ValueError
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return SqliteSaver(conn)
    except Exception as e:
        # If LangGraph is not installed or there's an error, return None
        # The system will work without checkpointing
        import logging
        logging.getLogger(__name__).debug(f"Could not create LangGraph checkpointer: {e}")
        return None

