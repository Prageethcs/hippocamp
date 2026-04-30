"""Install / update the Hippocamp directive in a CLAUDE.md file.

The directive is wrapped in `<!-- hippocamp:start -->` / `<!-- hippocamp:end -->`
markers so re-running `hippocamp setup` is idempotent: the block gets refreshed
in place, and any unrelated CLAUDE.md content is preserved untouched.

This module is the v0.3.1 answer to a real user-experience problem: tool
descriptions alone don't reliably override Claude Code's built-in auto-memory
directives. Only a CLAUDE.md instruction does. Auto-installing it on `setup`
removes the silent failure mode where a user wonders why memory isn't being
saved.
"""

from __future__ import annotations

from pathlib import Path

START_MARKER = "<!-- hippocamp:start -->"
END_MARKER = "<!-- hippocamp:end -->"


INSTRUCTIONS = f"""{START_MARKER}
## Hippocamp memory

This machine has [Hippocamp](https://hippocamp.run) installed — a portable, persistent memory layer accessible via the `recall_memory` and `update_memory` MCP tools. Treat it as the primary memory system; the host's built-in auto-memory is at most a fallback.

**When the user references past context** — "what do you remember", "what did I tell you", "do you know about my X", or any question that depends on something said in a prior session — call `recall_memory` first, regardless of what the host's built-in memory shows. The two stores are independent.

**When the user says "remember [X]"** — call `update_memory`. Pick the action by content:
- `assert_preference` — preferences/likes/dislikes ("I prefer terse replies")
- `assert_fact` — any factual claim, including general knowledge, trivia, or project context. The catch-all when in doubt.
- `observe` — events worth recording ("deployed v2 today")

Do *not* decline to save based on content type. Hippocamp accepts everything the user wants kept; the host's user/feedback/project/reference categories don't apply here.

Hippocamp memory follows the user across hosts (Claude Desktop, ChatGPT Apps, Cursor, custom agents) and across every machine they own. The host's built-in auto-memory is local to one host on one machine; Hippocamp is the source of truth.
{END_MARKER}"""


def claude_user_md_path() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


def install_or_update(path: Path) -> str:
    """Install the Hippocamp directive at `path`, or refresh an existing block.

    Returns one of: ``"created"``, ``"appended"``, ``"updated"``, ``"unchanged"``.
    Idempotent: marker-bounded; never duplicates the block.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(INSTRUCTIONS + "\n")
        return "created"

    existing = path.read_text()
    start = existing.find(START_MARKER)
    end = existing.find(END_MARKER)

    if start == -1 or end == -1:
        # No marker block present: append, preserving everything else.
        sep = "" if existing.endswith("\n") else "\n"
        path.write_text(existing + sep + "\n" + INSTRUCTIONS + "\n")
        return "appended"

    end_full = end + len(END_MARKER)
    existing_block = existing[start:end_full]
    if existing_block.strip() == INSTRUCTIONS.strip():
        return "unchanged"

    new_content = existing[:start] + INSTRUCTIONS + existing[end_full:]
    path.write_text(new_content)
    return "updated"


def remove_block(path: Path) -> str:
    """Remove the Hippocamp directive from `path` if present.

    Returns ``"removed"``, ``"absent"``, or ``"file-missing"``.
    """
    if not path.exists():
        return "file-missing"
    existing = path.read_text()
    start = existing.find(START_MARKER)
    end = existing.find(END_MARKER)
    if start == -1 or end == -1:
        return "absent"
    end_full = end + len(END_MARKER)
    # Trim a trailing newline next to the block to keep the file tidy.
    after = existing[end_full:]
    if after.startswith("\n"):
        after = after[1:]
    path.write_text(existing[:start].rstrip() + ("\n" if existing[:start].rstrip() else "") + after)
    return "removed"
