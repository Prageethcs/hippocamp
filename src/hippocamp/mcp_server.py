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
from typing import Any

from hippocamp.memory import Memory

DEFAULT_PATH = Path(
    os.environ.get("HIPPOCAMP_PATH", str(Path.home() / ".hippocamp" / "store.db"))
)


def main() -> None:
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    mem = Memory(path=str(DEFAULT_PATH))

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise SystemExit(
            "hippocamp-mcp requires the 'mcp' extra: pip install 'hippocamp[mcp]'"
        ) from e

    server = FastMCP("hippocamp")

    @server.tool()
    def recall_memory(
        query: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search Hippocamp memory. With no query, returns the inventory."""
        if query is None:
            return mem.inspect().model_dump()
        hits = mem.recall(query, kinds=kinds, limit=limit)
        return {"results": [h.model_dump() for h in hits]}

    @server.tool()
    def update_memory(
        action: str,
        text: str | None = None,
        kind: str = "episode",
        evidence: list[str] | None = None,
        strength: float = 1.0,
        id: str | None = None,
    ) -> dict[str, Any]:
        """Write or remove a memory.

        action ∈ {"observe", "assert_fact", "assert_preference", "forget"}.
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

    server.run()


if __name__ == "__main__":
    main()
