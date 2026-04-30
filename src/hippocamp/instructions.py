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

### Save proactively — don't wait for "remember"

Hippocamp is *ambient* memory. Save signals as they flow through the conversation, not just when the user explicitly invokes the magic word. Save anything matching:

- ✅ A preference clearly stated ("I prefer terse replies", "I dislike emoji")
- ✅ A stable fact about the user, project, or tooling ("we use Python 3.13", "I work at Acme Corp", "our DB is MongoDB")
- ✅ A decision, deadline, or commitment ("ship Friday", "switching to MongoDB", "deadline is March 5")
- ✅ A notable event ("just deployed v2", "completed onboarding")
- ✅ Anything the user explicitly framed as "remember/note/save" — catch-all override

Skip:
- ❌ Hypotheticals ("if we used Postgres...")
- ❌ Transient state ("debugging X right now", "I'm trying Y now")
- ❌ Code snippets / outputs / file contents
- ❌ Sarcasm or negations
- ❌ Things already covered in the current conversation context (it's already there)

Pick the action:
- `assert_preference` — preferences/likes/dislikes
- `assert_fact` — facts (user, project, tooling, decisions, deadlines, general knowledge when explicitly asked)
- `observe` — events worth keeping

### Announce what you saved

After every `update_memory` call, tell the user briefly what was captured: *"Saved to Hippocamp: preference (terse replies)"*. This keeps them in control without requiring them to invoke memory explicitly.

### Recall before you save

Before saving, consider whether a similar memory already exists. If you're unsure, call `recall_memory` with a focused query first — then either skip (already there), supersede (it's an update to an existing fact), or write fresh.

### When the user references past context

Always call `recall_memory` first — for "what do you remember", "what did I tell you", or any question depending on prior sessions. Hippocamp is independent of any host-built-in memory; check it regardless of what the host shows.

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
