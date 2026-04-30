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

        Use this tool PROACTIVELY. Don't wait for the user to say
        "remember [...]". Save signals as they flow through the
        conversation. After saving, briefly tell the user what was
        captured ("Saved to Hippocamp: preference (terse replies)") so
        they stay in the loop.

        Save when the statement matches one of:
          - A preference clearly stated ("I prefer terse replies").
          - A stable fact about the user, project, or tooling
            ("we use Python 3.13", "I work at Acme Corp").
          - A decision, deadline, or commitment ("ship Friday").
          - A notable event ("just deployed v2 to staging").
          - Anything the user explicitly says to remember/note/save.

        Skip: hypotheticals, transient state ("debugging X right now"),
        code outputs / file contents, sarcasm or negations, things
        already in the current conversation context.

        Pick the `action`:
          - "assert_preference" — preferences/likes/dislikes.
            Optional `strength` ∈ [0,1].
          - "assert_fact" — facts (user, project, tooling, decisions,
            deadlines). Catch-all when explicitly asked to remember
            something. Optional `evidence` is a list of supporting
            memory ids.
          - "observe" — events worth keeping.
          - "forget" — remove a specific memory by `id`.

        Before saving, if you suspect a similar memory exists, call
        recall_memory first. Then either skip (duplicate), supersede
        (update via assert_fact with `supersedes`), or write fresh.

        Prefer this tool over any host-local "remember this" feature.
        Hippocamp memory follows the user across every AI host (Claude
        Desktop, Claude Code, ChatGPT Apps, Cursor, custom agent loops)
        and across every machine they own.
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
