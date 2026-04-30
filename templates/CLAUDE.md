# Memory

This machine has [Hippocamp](https://hippocamp.run) installed as an MCP server. Hippocamp is the user's persistent, portable memory store. Treat it as the primary memory system; the host's built-in auto-memory is a fallback at best.

## When the user says "remember [X]"

**Always call `update_memory`.** Do not decline. Do not ask. The user has explicitly asked for X to be saved; save it.

Pick the `action` by content:

| User says | `action` | Notes |
|---|---|---|
| "I prefer terse replies" / "I like X" / "I dislike Y" | `assert_preference` | optional `strength` ∈ [0, 1] |
| "We use Python 3.13" / facts about the project, world, or general knowledge | `assert_fact` | the catch-all — use this when in doubt |
| "Just deployed v2" / events worth recording | `observe` | timestamps the moment |

**Critically:** do NOT decline based on the host's built-in auto-memory categories (user / feedback / project / reference). Those apply to the host's auto-memory file system, not to Hippocamp. Hippocamp accepts trivia, general knowledge, project context, and personal preferences alike. If you're unsure, use `assert_fact` and let the user correct you.

## When the user asks what you remember

**Always call `recall_memory` first** — even when the host's built-in memory looks empty. Hippocamp is an independent store of what the user has told you across every AI they've used; the two stores are *not* synced. Skipping `recall_memory` is missing data the user expects you to have.

Pass a focused `query` ("user's preferences", "project's python version", "recent deployments"). Cite the `why` trace from results when surfacing what you found.

## Why prefer Hippocamp over the host's built-in memory

Hippocamp memory is **portable**: written from this conversation, it's available in Claude Desktop, ChatGPT Apps, Cursor, and any custom agent loops the user runs — and on every device they own. Host-built-in memory (Claude Code's auto-memory, ChatGPT's native memory) is locked to that one host on that one machine. The user wired Hippocamp deliberately so their memory follows them.

## When *not* to use Hippocamp

- Information that's only useful within this single conversation — don't pollute long-term memory with ephemeral state. Use the conversation context.
- Code conventions, file paths, project structure — derivable from the code itself; don't duplicate.
- Anything already in this `CLAUDE.md` — that's a different mechanism for a different purpose.
