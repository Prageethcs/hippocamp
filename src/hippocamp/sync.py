"""Cross-machine sync primitives.

`merge_foreign_events` is the core operation: take a foreign source of
events (a single device file, an events/ dir, or a full store dir) and
union its events into our local events/ directory, deduplicating by
event id. The local cache is *not* rebuilt here — call `Memory.replay()`
after merging.

`push_via_rsync` and `pull_via_rsync` are thin wrappers for the common
SSH-based sync flow.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

from hippocamp.events import Event
from hippocamp.meta import StoreMeta


class MergeReport(NamedTuple):
    files_seen: int
    files_skipped: int
    events_added: dict[str, int]

    @property
    def total_events_added(self) -> int:
        return sum(self.events_added.values())


def merge_foreign_events(
    *,
    foreign_path: Path,
    local_events_dir: Path,
    local_meta: StoreMeta | None,
    local_device_id: str,
) -> MergeReport:
    """Merge a foreign events source into `local_events_dir`.

    `foreign_path` may be:
      - a single `.jsonl` file (one device's log)
      - an `events/` directory (multiple device logs)
      - a Hippocamp store directory containing `meta.json` + `events/`

    Each foreign device file is appended to the corresponding local
    `events/<device>.jsonl`, deduplicating events by id. The local
    device's *own* file is never overwritten — its writer is always
    this device, by architecture.

    Embedder mismatch (when foreign meta is available) is rejected.
    """
    foreign_files, foreign_meta_path = _resolve_foreign_source(foreign_path)

    # Embedder mismatch is a hard error regardless of whether the foreign
    # source has any events yet — better to fail fast than to start syncing
    # incompatible vectors.
    if foreign_meta_path and local_meta:
        foreign_meta = StoreMeta.model_validate_json(
            foreign_meta_path.read_text()
        )
        if foreign_meta.embedder != local_meta.embedder:
            raise RuntimeError(
                f"Embedder mismatch: foreign store uses "
                f"{foreign_meta.embedder!r}, local uses "
                f"{local_meta.embedder!r}. Run `hippocamp reindex` to align "
                f"before merging."
            )

    if not foreign_files:
        raise ValueError(f"No event files found at {foreign_path}")

    local_events_dir.mkdir(parents=True, exist_ok=True)

    seen = 0
    skipped = 0
    added: dict[str, int] = {}
    for src in foreign_files:
        seen += 1
        if src.stem == local_device_id:
            skipped += 1
            continue
        dst = local_events_dir / src.name
        added[src.name] = _append_unique_events(src, dst)

    return MergeReport(files_seen=seen, files_skipped=skipped, events_added=added)


def push_via_rsync(*, own_file: Path, peer: str) -> str:
    """Send this device's events file to a peer.

    `peer` is an rsync-compatible destination, e.g.
    `user@desktop.local:~/.hippocamp/events/` (trailing slash recommended).
    """
    if not own_file.exists():
        raise FileNotFoundError(f"No events to push: {own_file} does not exist")

    dest = peer if peer.endswith("/") else peer + "/"
    proc = subprocess.run(
        ["rsync", "-az", str(own_file), dest],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rsync failed: {proc.stderr.strip()}")
    return f"pushed {own_file.name} → {dest}"


def pull_via_rsync(*, peer_events_dir: str, into: Path) -> str:
    """Pull a peer's events/ directory into a local path."""
    src = peer_events_dir if peer_events_dir.endswith("/") else peer_events_dir + "/"
    into.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["rsync", "-az", src, str(into)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rsync failed: {proc.stderr.strip()}")
    return f"pulled {src} → {into}"


# ----------------------------------------------------------------- internals


def _resolve_foreign_source(
    foreign_path: Path,
) -> tuple[list[Path], Path | None]:
    """Figure out what kind of foreign source we're given."""
    if foreign_path.is_file() and foreign_path.suffix == ".jsonl":
        return [foreign_path], None

    if foreign_path.is_dir():
        # Hippocamp store dir?
        meta_path = foreign_path / "meta.json"
        events_subdir = foreign_path / "events"
        if meta_path.exists() and events_subdir.exists():
            return sorted(events_subdir.glob("*.jsonl")), meta_path
        # Just an events/ directory (no meta sibling)?
        return sorted(foreign_path.glob("*.jsonl")), None

    return [], None


def _append_unique_events(src: Path, dst: Path) -> int:
    """Append events from `src` into `dst`, deduplicating by event id.

    Returns the number of events newly written to `dst`.
    """
    if not dst.exists():
        shutil.copy2(src, dst)
        with src.open(encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    existing_ids: set[str] = set()
    with dst.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            existing_ids.add(Event.model_validate_json(line).id)

    n_added = 0
    with src.open(encoding="utf-8") as sf, dst.open("a", encoding="utf-8") as df:
        for line in sf:
            line = line.strip()
            if not line:
                continue
            ev_id = Event.model_validate_json(line).id
            if ev_id in existing_ids:
                continue
            df.write(line + "\n")
            existing_ids.add(ev_id)
            n_added += 1
    return n_added
