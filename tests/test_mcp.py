"""End-to-end test of the MCP tool surface.

Drives the same `recall_memory` and `update_memory` callables that the
MCP host (Claude Desktop / Cursor / ChatGPT Apps) calls, without
spinning up a real MCP transport.
"""

from __future__ import annotations

from hippocamp import Memory
from hippocamp.embedders import HashEmbedder
from hippocamp.mcp_server import build_tools


def _tools():
    mem = Memory(path=":memory:", embedder=HashEmbedder())
    return mem, build_tools(mem)


def test_observe_then_recall_via_mcp_tools():
    _, tools = _tools()

    r = tools["update_memory"](action="observe", text="user wants to deploy to GCP")
    assert r["ok"] is True
    assert r["action"] == "observe"
    ep_id = r["id"]
    assert ep_id.startswith("ep_")

    r = tools["recall_memory"](query="deploy")
    assert "results" in r
    assert any(h["id"] == ep_id for h in r["results"])
    top = r["results"][0]
    assert "why" in top
    assert "note" in top["why"]


def test_assert_fact_and_forget_via_mcp_tools():
    _, tools = _tools()

    r = tools["update_memory"](action="assert_fact", text="project uses Python 3.13")
    fact_id = r["id"]
    assert fact_id.startswith("fa_")

    r = tools["update_memory"](action="forget", id=fact_id)
    assert r["ok"] is True
    assert r["action"] == "forget"

    r = tools["recall_memory"](query="python", kinds=["fact"])
    assert not any(h["id"] == fact_id for h in r["results"])


def test_recall_with_no_query_returns_inventory():
    _, tools = _tools()
    tools["update_memory"](action="observe", text="one")
    tools["update_memory"](action="observe", text="two")
    tools["update_memory"](action="assert_fact", text="a fact")

    r = tools["recall_memory"]()
    assert r["episodes"] == 2
    assert r["facts"] == 1
    assert r["preferences"] == 0


def test_unknown_action_raises():
    _, tools = _tools()
    try:
        tools["update_memory"](action="bogus", text="x")
    except ValueError as e:
        assert "unknown action" in str(e)
    else:
        raise AssertionError("expected ValueError for unknown action")


def test_forget_without_id_raises():
    _, tools = _tools()
    try:
        tools["update_memory"](action="forget")
    except ValueError as e:
        assert "requires an id" in str(e)
    else:
        raise AssertionError("expected ValueError when 'forget' has no id")
