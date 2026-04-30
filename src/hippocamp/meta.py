"""Store-level metadata (`meta.json`) and per-device id (`device.json`).

`meta.json` records the embedder this store is committed to. All devices
syncing the same store must agree on it; otherwise recall would drift across
devices. A mismatch is a hard error with a clear remediation message.

`device.json` lives at `~/.hippocamp/device.json` and gives this machine a
stable id used in every event it writes.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


SCHEMA_VERSION = 1


class StoreMeta(BaseModel):
    embedder: str
    store_id: str
    schema_version: int = SCHEMA_VERSION
    created_at: datetime


def _new_id() -> str:
    return uuid.uuid4().hex


def load_or_init_meta(
    meta_path: Path,
    embedder_name: str,
    *,
    force: bool = False,
) -> StoreMeta:
    """Load `meta.json` if present, else create one. Reject embedder mismatch.

    A mismatch means another device wrote this store with a different
    embedder. Cross-device recall would be inconsistent until aligned, so
    we refuse to open the store rather than silently drift.

    Pass `force=True` from `hippocamp reindex --embedder NEW` to bypass
    the check during a deliberate embedder switch.
    """
    if meta_path.exists():
        meta = StoreMeta.model_validate_json(meta_path.read_text())
        if not force and meta.embedder != embedder_name:
            raise RuntimeError(
                f"Embedder mismatch at {meta_path.parent}: store committed to "
                f"{meta.embedder!r}, this client uses {embedder_name!r}. "
                f"Run `hippocamp reindex --embedder {embedder_name}` to migrate, "
                f"or open with the matching embedder."
            )
        return meta

    meta = StoreMeta(
        embedder=embedder_name,
        store_id=_new_id(),
        created_at=datetime.now(timezone.utc),
    )
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(meta.model_dump_json(indent=2) + "\n")
    return meta


def write_meta(meta_path: Path, meta: StoreMeta) -> None:
    """Persist a meta object atomically."""
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
    tmp.write_text(meta.model_dump_json(indent=2) + "\n")
    tmp.replace(meta_path)


def load_or_init_device_id(device_path: Path | None = None) -> str:
    """Return this device's stable id, creating one on first call.

    Default location: `~/.hippocamp/device.json`. The same id is used
    across every Hippocamp store this machine accesses.
    """
    if device_path is None:
        device_path = Path.home() / ".hippocamp" / "device.json"

    if device_path.exists():
        return json.loads(device_path.read_text())["device_id"]

    device_id = _new_id()
    device_path.parent.mkdir(parents=True, exist_ok=True)
    device_path.write_text(
        json.dumps({"device_id": device_id}, indent=2) + "\n"
    )
    return device_id
