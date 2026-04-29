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
    try:
        result = fn()
    except RuntimeError as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1

    where = result.config_path or "(via host CLI)"
    print(f"hippocamp setup {args.host}: {result.action} at {where}")
    if result.notes:
        print(result.notes)
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


def _cmd_replay(args: argparse.Namespace) -> int:
    mem = _open_memory(args.path)
    if mem.events_dir is None:
        print("hippocamp: cannot replay an in-memory store", file=sys.stderr)
        return 1
    n = mem.replay()
    print(f"replayed {n} events into {mem._path_str}")
    return 0


def _cmd_sync_merge(args: argparse.Namespace) -> int:
    mem = _open_memory(args.path)
    if mem.events_dir is None or mem.meta is None:
        print("hippocamp: cannot merge into an in-memory store", file=sys.stderr)
        return 1

    try:
        report = merge_foreign_events(
            foreign_path=Path(args.foreign).expanduser(),
            local_events_dir=mem.events_dir,
            local_meta=mem.meta,
            local_device_id=mem.device_id,
        )
    except (ValueError, RuntimeError) as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1

    print(_format_merge_report(report))

    if not args.no_replay:
        n = mem.replay()
        print(f"replayed {n} events")
    return 0


def _cmd_sync_push(args: argparse.Namespace) -> int:
    mem = _open_memory(args.path)
    if mem.events_own_file is None:
        print("hippocamp: cannot push from an in-memory store", file=sys.stderr)
        return 1
    try:
        msg = push_via_rsync(own_file=mem.events_own_file, peer=args.peer)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"hippocamp: {e}", file=sys.stderr)
        return 1
    print(msg)
    return 0


def _cmd_sync_pull(args: argparse.Namespace) -> int:
    mem = _open_memory(args.path)
    if mem.events_dir is None or mem.meta is None:
        print("hippocamp: cannot pull into an in-memory store", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            msg = pull_via_rsync(peer_events_dir=args.peer, into=tmp_path)
        except RuntimeError as e:
            print(f"hippocamp: {e}", file=sys.stderr)
            return 1
        print(msg)

        report = merge_foreign_events(
            foreign_path=tmp_path,
            local_events_dir=mem.events_dir,
            local_meta=mem.meta,
            local_device_id=mem.device_id,
        )
        print(_format_merge_report(report))

    if not args.no_replay:
        n = mem.replay()
        print(f"replayed {n} events")
    return 0


def _cmd_sync_status(args: argparse.Namespace) -> int:
    mem = _open_memory(args.path)
    if mem.events_dir is None:
        print("hippocamp: in-memory store; no sync state")
        return 0

    print(f"store:        {mem._path_str}")
    print(f"device id:    {mem.device_id}")
    print(f"embedder:     {mem.meta.embedder if mem.meta else '(none)'}")
    print(f"events dir:   {mem.events_dir}")

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
    p_setup.set_defaults(func=_cmd_setup)

    p_inspect = sub.add_parser("inspect", help="Show memory contents.")
    p_inspect.add_argument("--path", default=None, help="Path to store.db")
    p_inspect.add_argument("--query", default=None, help="Optional recall query")
    p_inspect.add_argument("--limit", type=int, default=5)
    p_inspect.set_defaults(func=_cmd_inspect)

    p_replay = sub.add_parser(
        "replay",
        help="Wipe the cache and rebuild it from the event log.",
    )
    p_replay.add_argument("--path", default=None, help="Path to store.db")
    p_replay.set_defaults(func=_cmd_replay)

    p_sync = sub.add_parser("sync", help="Sync events with another machine.")
    sync_sub = p_sync.add_subparsers(dest="sync_cmd", required=True)

    p_merge = sync_sub.add_parser(
        "merge",
        help="Merge a foreign events source (file, events/ dir, or store dir).",
    )
    p_merge.add_argument("foreign", help="Path to foreign events source")
    p_merge.add_argument("--path", default=None, help="Path to local store.db")
    p_merge.add_argument(
        "--no-replay",
        action="store_true",
        help="Skip cache rebuild after merging",
    )
    p_merge.set_defaults(func=_cmd_sync_merge)

    p_push = sync_sub.add_parser(
        "push",
        help="rsync this device's events file to a peer.",
    )
    p_push.add_argument(
        "peer",
        help="rsync destination (e.g. user@host:~/.hippocamp/events/)",
    )
    p_push.add_argument("--path", default=None, help="Path to local store.db")
    p_push.set_defaults(func=_cmd_sync_push)

    p_pull = sync_sub.add_parser(
        "pull",
        help="rsync a peer's events/ dir locally and merge it in.",
    )
    p_pull.add_argument(
        "peer",
        help="rsync source (e.g. user@host:~/.hippocamp/events/)",
    )
    p_pull.add_argument("--path", default=None, help="Path to local store.db")
    p_pull.add_argument(
        "--no-replay",
        action="store_true",
        help="Skip cache rebuild after merging",
    )
    p_pull.set_defaults(func=_cmd_sync_pull)

    p_status = sync_sub.add_parser("status", help="Show sync state.")
    p_status.add_argument("--path", default=None, help="Path to local store.db")
    p_status.set_defaults(func=_cmd_sync_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
