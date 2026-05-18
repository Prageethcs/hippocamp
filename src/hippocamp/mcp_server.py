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

import argparse
import os
from pathlib import Path
from typing import Any, Callable

from hippocamp import __version__
from hippocamp.memory import Memory

DEFAULT_PATH = Path(
    os.environ.get("HIPPOCAMP_PATH", str(Path.home() / ".hippocamp"))
)


def build_tools(
    mem: Memory,
    *,
    llm: Any = None,
) -> dict[str, Callable[..., dict[str, Any]]]:
    """Build the MCP tool callables bound to a Memory instance.

    Exposed at module level so tests can drive the same handlers the
    MCP host calls, without spinning up a real MCP transport.

    If `llm` is provided, the `reflect_memory` tool is exposed; otherwise
    it raises a clear error when called. `Memory(llm=...)` would also
    work, but threading the LLM through `build_tools` keeps the tool
    surface composable for tests.
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

    def reflect_memory(since: str | None = None) -> dict[str, Any]:
        """Distil recent episodes into facts/preferences/reflections.

        Use this tool RARELY — typically not in response to a single user
        message. Reflection is a background hygiene operation that scans
        recent episodes, extracts durable user-modelling content via an
        LLM, and writes it back as facts/preferences/reflections so future
        recall surfaces clean signal instead of raw episode noise.

        Call when:
          - The user explicitly asks ("consolidate my memory", "refresh
            what you know about me", "summarise recent context").
          - Driven by a cron / launchd / scheduler running on a fixed
            cadence (typical pattern: every 6 h).

        Skip when:
          - You're handling a normal conversational turn — recall_memory
            is the right tool, not reflect_memory.
          - The store has fewer than ~5 new episodes since the last pass
            (reflect will skip anyway, but you save the round-trip).

        Pass `since` (ISO 8601) to control the cutoff. Default: the
        store's `last_reflect_at` if recorded, else 7 days ago.

        Requires the server to be configured with an LLM. If not, the
        tool raises a clear error explaining how to enable it.
        """
        if llm is None:
            raise RuntimeError(
                "reflect_memory is unavailable: the MCP server has no LLM "
                "configured. Set ANTHROPIC_API_KEY in the server env, or "
                "build_tools(mem, llm=...) explicitly."
            )
        # Pass through to Memory.reflect — but inject our own llm in case
        # the Memory was built without one.
        if mem._llm is None:
            mem._llm = llm  # type: ignore[attr-defined]
        report = mem.reflect(since=since)
        return report.model_dump()

    return {
        "recall_memory": recall_memory,
        "update_memory": update_memory,
        "reflect_memory": reflect_memory,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hippocamp-mcp",
        description=(
            "Hippocamp MCP server — exposes recall_memory, update_memory, "
            "and reflect_memory tools over stdio."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hippocamp-mcp {__version__}",
    )
    parser.parse_args()

    DEFAULT_PATH.mkdir(parents=True, exist_ok=True)
    mem = Memory(path=str(DEFAULT_PATH))

    # Lazy LLM init: only used by reflect_memory. Server starts fine
    # without one — the tool just raises a clear error if called.
    llm: Any = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from hippocamp.reflect import default_anthropic_llm
            llm = default_anthropic_llm()
        except RuntimeError:
            llm = None  # missing extras / key — silently fall back

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit(
            "hippocamp-mcp requires the 'mcp' extra: pip install 'hippocamp[mcp]'"
        ) from e

    server = FastMCP("hippocamp")
    for name, fn in build_tools(mem, llm=llm).items():
        server.tool(name=name)(fn)
    server.run()


if __name__ == "__main__":
    main()
