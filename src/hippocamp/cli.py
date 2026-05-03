"""Hippocamp CLI: `hippocamp setup`, `inspect`, `replay`, `sync`.

Run `hippocamp --help` for the full subcommand list.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from hippocamp import __version__
from hippocamp.mcp_server import DEFAULT_PATH
from hippocamp.memory import Memory
from hippocamp.setup import HOSTS, SETUP_FUNCS
from hippocamp.sync import (
    MergeReport,
    merge_foreign_events,
    pull_via_rsync,
    push_via_rsync,
)


def _resolve_path(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg)
    env = os.environ.get("HIPPOCAMP_PATH")
    if env:
        return Path(env)
    return DEFAULT_PATH


def _open_memory(path_arg: str | None) -> Memory:
    return Memory(path=str(_resolve_path(path_arg)))


# ------------------------------------------------------------------ commands


def _cmd_setup(args: argparse.Namespace) -> int:
    fn = SETUP_FUNCS[args.host]
    kwargs: dict = {"path": args.path, "cache_dir": args.cache_dir}
    if args.host == "claude":
        kwargs["install_instructions"] = not args.no_instructions
        if args.project_instructions:
            kwargs["project_instructions_dir"] = args.project_instructions

    try:
        result = fn(**kwargs)
    except RuntimeError as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1

    # `setup claude` returns a list (one entry per detected host); the
    # single-host setups (claude-desktop, cursor, gemini-cli) return a
    # single SetupResult.
    results = result if isinstance(result, list) else [result]

    if args.path:
        print(f"store dir:  {args.path}")
    if args.cache_dir:
        print(f"cache dir:  {args.cache_dir}")

    for r in results:
        where = r.config_path or "(via host CLI)"
        print()
        print(f"→ {r.host}: {r.action} at {where}")
        if r.notes:
            for line in r.notes.split("\n"):
                if line.strip():
                    print(f"  {line}")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    path = _resolve_path(args.path)
    if not path.exists():
        print(f"hippocamp: no store found at {path}")
        return 1

    mem = Memory(path=str(path))
    inv = mem.inspect()
    print(json.dumps(inv.model_dump(), indent=2, default=str))

    if args.query:
        print(f"\n--- recall({args.query!r}, limit={args.limit}) ---")
        hits = mem.recall(args.query, limit=args.limit)
        for h in hits:
            print(f"[{h.kind}] {h.text}")
            print(f"  score={h.score:.3f} ({h.why.note})")
    return 0


def _cmd_instructions(args: argparse.Namespace) -> int:
    from hippocamp.instructions import get_instructions

    print(get_instructions(short=args.short))
    return 0


def _resolve_embedder(name: str | None):
    """Look up a named embedder. Add new ones here as they're added."""
    if name is None:
        return None
    name_lc = name.lower()
    if name_lc in ("qwen", "qwen3", "qwen3-embedding-0.6b"):
        from hippocamp.embedders import Qwen3Embedder
        return Qwen3Embedder()
    if name_lc in ("bge-small", "bge-small-en", "bge-small-en-v1.5"):
        from hippocamp.embedders import BgeSmallEmbedder
        return BgeSmallEmbedder()
    if name_lc in ("hash", "hash-32"):
        from hippocamp.embedders import HashEmbedder
        return HashEmbedder()
    raise ValueError(f"unknown embedder: {name!r}")


def _cmd_reindex(args: argparse.Namespace) -> int:
    path = _resolve_path(args.path)
    if not path.exists():
        print(f"hippocamp: no store found at {path}", file=sys.stderr)
        return 1

    try:
        embedder = _resolve_embedder(args.embedder)
    except ValueError as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1

    mem = Memory(
        path=str(path),
        embedder=embedder,
        force_embedder=embedder is not None,
    )
    if mem.events_dir is None:
        print("hippocamp: cannot reindex an in-memory store", file=sys.stderr)
        return 1

    n = mem.reindex()
    print(f"reindexed {n} memories with embedder {mem.meta.embedder!r}")
    return 0


def _is_remote_target(target: str) -> bool:
    """`user@host:path` or `host:path` (with no existing local path of that name)."""
    if Path(target).expanduser().exists():
        return False
    return "@" in target and ":" in target


def _peer_events_dir(peer: str) -> str:
    """Turn a peer spec (`user@host[:path]`) into an rsync `events/` URL."""
    user_host, _, path = peer.partition(":")
    path = path.strip() or "~/.hippocamp"
    return f"{user_host}:{path.rstrip('/')}/events/"


def _cmd_sync(args: argparse.Namespace) -> int:
    """One smart sync command. Behaviour depends on `target`:

      no target  → rebuild local cache from existing events (cloud-folder case).
      local path → merge events from that path, then rebuild.
      remote     → bidirectional rsync (push our device file, pull peers'),
                   then rebuild.
    """
    mem = _open_memory(args.path)
    if mem.events_dir is None or mem.meta is None:
        print("hippocamp: in-memory store; nothing to sync", file=sys.stderr)
        return 1

    target = args.target

    if target is None:
        n = mem.replay()
        print(f"rebuilt local cache ({n} events)")
        return 0

    if _is_remote_target(target):
        return _sync_remote(mem, target, no_replay=args.no_replay)

    return _sync_local(mem, Path(target).expanduser(), no_replay=args.no_replay)


def _sync_local(mem, foreign_path: Path, *, no_replay: bool) -> int:
    try:
        report = merge_foreign_events(
            foreign_path=foreign_path,
            local_events_dir=mem.events_dir,
            local_meta=mem.meta,
            local_device_id=mem.device_id,
        )
    except (ValueError, RuntimeError) as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1

    print(_format_merge_report(report))

    if not no_replay:
        n = mem.replay()
        print(f"rebuilt cache ({n} events)")
    return 0


def _sync_remote(mem, peer: str, *, no_replay: bool) -> int:
    peer_events = _peer_events_dir(peer)

    try:
        push_via_rsync(own_file=mem.events_own_file, peer=peer_events)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"hippocamp: push failed: {e}", file=sys.stderr)
        return 1
    print(f"  → pushed {mem.events_own_file.name}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            pull_via_rsync(peer_events_dir=peer_events, into=tmp_path)
        except RuntimeError as e:
            print(f"hippocamp: pull failed: {e}", file=sys.stderr)
            return 1

        report = merge_foreign_events(
            foreign_path=tmp_path,
            local_events_dir=mem.events_dir,
            local_meta=mem.meta,
            local_device_id=mem.device_id,
        )
        print(_format_merge_report(report))

    if not no_replay:
        n = mem.replay()
        print(f"rebuilt cache ({n} events)")
    return 0


def _cmd_reflect(args: argparse.Namespace) -> int:
    path = _resolve_path(args.path)
    if not path.exists():
        print(f"hippocamp: no store found at {path}", file=sys.stderr)
        return 1

    try:
        llm = _resolve_llm(args.llm)
    except (ValueError, RuntimeError) as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1

    mem = Memory(path=str(path), llm=llm)
    try:
        report = mem.reflect(since=args.since)
    except RuntimeError as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1

    print(json.dumps(report.model_dump(), indent=2, default=str))
    return 0


def _resolve_llm(name: str | None):
    """Look up a named LLM adapter. Default: anthropic Claude Haiku.

    Hippocamp ships a thin Anthropic adapter; users wanting a different
    provider should call `Memory(llm=...)` from Python directly.
    """
    name = (name or "anthropic").lower()
    if name in ("anthropic", "claude"):
        from hippocamp.reflect import default_anthropic_llm
        return default_anthropic_llm()
    raise ValueError(f"unknown llm: {name!r}")


def _cmd_status(args: argparse.Namespace) -> int:
    mem = _open_memory(args.path)
    if mem.events_dir is None:
        print("hippocamp: in-memory store; no sync state")
        return 0

    print(f"store dir:    {mem.store_dir}")
    print(f"events dir:   {mem.events_dir}")
    print(f"cache path:   {mem.cache_path}")
    print(f"device id:    {mem.device_id}")
    print(f"embedder:     {mem.meta.embedder if mem.meta else '(none)'}")

    files = sorted(mem.events_dir.glob("*.jsonl")) if mem.events_dir.exists() else []
    if not files:
        print("device files: (none)")
        return 0

    print("device files:")
    for f in files:
        n_lines = sum(1 for line in f.open(encoding="utf-8") if line.strip())
        own_marker = "  (this device)" if f.stem == mem.device_id else ""
        print(f"  {f.name:40s}  {n_lines:6d} events{own_marker}")
    return 0


# ---------------------------------------------------------------- formatting


def _format_merge_report(report: MergeReport) -> str:
    if report.total_events_added == 0 and report.files_skipped == 0:
        return "no new events to merge"
    lines = [
        f"merged {report.files_seen} foreign device file(s) "
        f"({report.files_skipped} skipped as own)"
    ]
    for name, n in sorted(report.events_added.items()):
        if n > 0:
            lines.append(f"  + {n:6d} new events from {name}")
    if report.total_events_added == 0:
        lines.append("  (all events already present)")
    return "\n".join(lines)


# ------------------------------------------------------------------ entry pt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hippocamp",
        description="Local-first portable memory for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"hippocamp {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="Wire Hippocamp into an AI host.")
    p_setup.add_argument("host", choices=HOSTS, help="Which host to configure.")
    p_setup.add_argument(
        "--path",
        default=None,
        help="Store directory for events + meta (e.g. ~/Dropbox/Hippocamp). "
        "Passed to the host as HIPPOCAMP_PATH.",
    )
    p_setup.add_argument(
        "--cache-dir",
        default=None,
        help="Local-only cache base dir (defaults to OS cache dir). "
        "Passed to the host as HIPPOCAMP_CACHE_DIR.",
    )
    p_setup.add_argument(
        "--no-instructions",
        action="store_true",
        help="(Claude Code only) skip writing the Hippocamp directive to "
        "~/.claude/CLAUDE.md.",
    )
    p_setup.add_argument(
        "--project-instructions",
        metavar="DIR",
        default=None,
        help="(Claude Code only) also write the directive to <DIR>/CLAUDE.md.",
    )
    p_setup.set_defaults(func=_cmd_setup)

    p_inspect = sub.add_parser("inspect", help="Show memory contents.")
    p_inspect.add_argument("--path", default=None, help="Path to store.db")
    p_inspect.add_argument("--query", default=None, help="Optional recall query")
    p_inspect.add_argument("--limit", type=int, default=5)
    p_inspect.set_defaults(func=_cmd_inspect)

    p_sync = sub.add_parser(
        "sync",
        help="Sync local cache with events. With a target, also fetch/exchange first.",
    )
    p_sync.add_argument(
        "target",
        nargs="?",
        default=None,
        help="(optional) Local path or peer (user@host[:path]). "
        "Omit to just rebuild local cache from existing events.",
    )
    p_sync.add_argument("--path", default=None, help="Path to local store dir")
    p_sync.add_argument(
        "--no-replay",
        action="store_true",
        help="Skip cache rebuild",
    )
    p_sync.set_defaults(func=_cmd_sync)

    p_status = sub.add_parser("status", help="Show what's stored and where.")
    p_status.add_argument("--path", default=None, help="Path to store dir")
    p_status.set_defaults(func=_cmd_status)

    p_instructions = sub.add_parser(
        "instructions",
        help="Print the Hippocamp directive (for pasting into Claude Desktop / "
        "ChatGPT custom instructions).",
    )
    p_instructions.add_argument(
        "--short",
        action="store_true",
        help="Compact 4-paragraph version (best for Claude Desktop's Profile field).",
    )
    p_instructions.set_defaults(func=_cmd_instructions)

    p_reindex = sub.add_parser(
        "reindex",
        help="Recompute embeddings for all active memories.",
    )
    p_reindex.add_argument("--path", default=None, help="Path to the store dir")
    p_reindex.add_argument(
        "--embedder",
        default=None,
        help="Switch to a named embedder (e.g. bge-small). Updates meta.json.",
    )
    p_reindex.set_defaults(func=_cmd_reindex)

    p_reflect = sub.add_parser(
        "reflect",
        help="Distil recent episodes into facts/preferences/reflections via an LLM.",
    )
    p_reflect.add_argument("--path", default=None, help="Path to the store dir")
    p_reflect.add_argument(
        "--since",
        default=None,
        help="ISO timestamp cutoff. Default: meta.last_reflect_at, else now-7d.",
    )
    p_reflect.add_argument(
        "--llm",
        default="anthropic",
        help="LLM adapter to use. Currently: 'anthropic' (default). "
        "Set ANTHROPIC_API_KEY in environment.",
    )
    p_reflect.set_defaults(func=_cmd_reflect)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
