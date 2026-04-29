"""Hippocamp CLI: `hippocamp setup HOST` and `hippocamp inspect`.

Run `hippocamp --help` for a full list of subcommands.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hippocamp import __version__
from hippocamp.memory import Memory
from hippocamp.mcp_server import DEFAULT_PATH
from hippocamp.setup import HOSTS, SETUP_FUNCS


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
    path = Path(args.path) if args.path else DEFAULT_PATH
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hippocamp",
        description="Local-first portable memory for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"hippocamp {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="Wire Hippocamp into an AI host.")
    p_setup.add_argument(
        "host",
        choices=HOSTS,
        help="Which host to configure.",
    )
    p_setup.set_defaults(func=_cmd_setup)

    p_inspect = sub.add_parser("inspect", help="Show memory contents.")
    p_inspect.add_argument("--path", default=None, help="Path to store.db")
    p_inspect.add_argument("--query", default=None, help="Optional recall query")
    p_inspect.add_argument("--limit", type=int, default=5)
    p_inspect.set_defaults(func=_cmd_inspect)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
