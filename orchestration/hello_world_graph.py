"""Phase 0 test per docs/plan/section_orchestration.md section 3: a one-node
no-op LangGraph graph that runs and checkpoints to orchestration/checkpoints.db,
proving the orchestration/state.py + SqliteSaver pattern works end-to-end
before Phase 3 wires in the real 8-specialist-agent graph.

Usage: python orchestration/hello_world_graph.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_DB = REPO_ROOT / "orchestration" / "checkpoints.db"


class HelloState(TypedDict):
    message: str
    visited: bool


def noop_node(state: HelloState) -> HelloState:
    return {"message": state["message"], "visited": True}


def build_graph():
    graph = StateGraph(HelloState)
    graph.add_node("noop", noop_node)
    graph.add_edge(START, "noop")
    graph.add_edge("noop", END)
    return graph


def main() -> None:
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CHECKPOINT_DB), check_same_thread=False)
    saver = SqliteSaver(conn)
    app = build_graph().compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "hello-world-smoke-test"}}
    result = app.invoke({"message": "market-alpha-agents Phase 0 smoke test", "visited": False}, config)
    print(f"Graph result: {result}")

    checkpoints = list(saver.list(config))
    print(f"Checkpoints persisted to {CHECKPOINT_DB}: {len(checkpoints)}")
    assert len(checkpoints) > 0, "expected at least one checkpoint to be written"
    assert result["visited"] is True

    conn.close()
    print("Phase 0 LangGraph checkpoint smoke test: PASSED")


if __name__ == "__main__":
    main()
