"""Hippocamp MCP server — two-tool surface.

Run as `hippocamp-mcp` (after `pip install 'hippocamp[mcp]'`), or wire
into Claude Desktop / Cursor / ChatGPT Apps via:

    {
      "mcpServers": {
        "hippocamp": { "command": "hippocamp-mcp" }
      }
    }

Memory lives at $HIPPOCAMP_PATH (default ~/.hippocamp/store.db). Nothing
ever leaves the user's machine.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from hippocamp.memory import Memory

DEFAULT_PATH = Path(
    os.environ.get("HIPPOCAMP_PATH", str(Path.home() / ".hippocamp"))
)


def build_tools(mem: Memory) -> dict[str, Callable[..., dict[str, Any]]]:
    """Build the MCP tool callables bound to a Memory instance.

    Exposed at module level so tests can drive the same handlers the
    MCP host calls, without spinning up a real MCP transport.
    """

    def recall_memory(
        query: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Recall the user's portable, persistent memory from Hippocamp.

        Use this tool whenever the user references something said in a
        past conversation, asks what you know about their preferences,
        project, tools, or past events, or whenever you need context
        about the user that isn't already in the current conversation.

        IMPORTANT: Hippocamp is *independent* of any host-local memory
        feature. Even when the host's built-in memory looks empty, you
        must still check Hippocamp — the two stores aren't synced.
        Hippocamp may contain what the user has written across every
        AI host they've used (Claude Desktop, Claude Code, ChatGPT
        Apps, Cursor, custom agents). Failing to call this tool means
        missing data the user expects you to have.

        Pass a `query` describing what you want to recall ("user's
        preferred reply length", "python version of current project",
        "recent deployment events"). With no query, returns inventory
        counts for the four memory kinds.

        Optional `kinds` filter accepts one or more of: "episode",
        "fact", "preference", "reflection".

        Returns ranked memories with a `why` trace that explains how
        each score was composed (similarity + recency + kind-boost +
        salience). Cite the `why` when surfacing results.
        """
        if query is None:
            return mem.inspect().model_dump()
        hits = mem.recall(query, kinds=kinds, limit=limit)
        return {"results": [h.model_dump() for h in hits]}

    def update_memory(
        action: str,
        text: str | None = None,
        kind: str = "episode",
        evidence: list[str] | None = None,
        strength: float = 1.0,
        id: str | None = None,
    ) -> dict[str, Any]:
        """Write or remove a memory in Hippocamp — the user's portable memory.

        Use this tool whenever the user states something worth keeping:
        a preference about themselves, a stable fact about their project
        or context, or an event worth recording. Memory written here is
        available in every other host the user connects (Claude Desktop,
        Claude Code, ChatGPT Apps, Cursor, custom agent loops) — not
        just this conversation.

        Prefer this tool over any host-local "remember this" feature
        when Hippocamp is available. The user has wired Hippocamp
        deliberately so their memory survives switching hosts and models.

        Pick the `action` by what the user is telling you:
          - "assert_preference" — user states a preference about themselves
            ("I prefer terse replies", "I dislike emoji"). Optional
            `strength` ∈ [0, 1] for confidence.
          - "assert_fact" — user asserts a stable fact about their project,
            tools, or context ("we use Python 3.13", "auth migration
            ships March 5"). Optional `evidence` is a list of supporting
            memory ids.
          - "observe" — record an event worth keeping ("deployed v2 to
            staging today", "user asked about GCP deployment").
          - "forget" — remove a specific memory by `id`.
        """
        if action == "observe":
            mid = mem.observe(text or "")
        elif action == "assert_fact":
            mid = mem.assert_fact(text or "", evidence=evidence)
        elif action == "assert_preference":
            mid = mem.assert_preference(text or "", strength=strength)
        elif action == "forget":
            if not id:
                raise ValueError("'forget' requires an id")
            mem.forget(id)
            return {"ok": True, "id": id, "action": "forget"}
        else:
            raise ValueError(f"unknown action: {action}")

        return {"ok": True, "id": mid, "action": action}

    return {"recall_memory": recall_memory, "update_memory": update_memory}


def main() -> None:
    DEFAULT_PATH.mkdir(parents=True, exist_ok=True)
    mem = Memory(path=str(DEFAULT_PATH))

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit(
            "hippocamp-mcp requires the 'mcp' extra: pip install 'hippocamp[mcp]'"
        ) from e

    server = FastMCP("hippocamp")
    for name, fn in build_tools(mem).items():
        server.tool(name=name)(fn)
    server.run()


if __name__ == "__main__":
    main()
