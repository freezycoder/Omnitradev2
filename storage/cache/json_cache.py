from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any


_log = logging.getLogger(__name__)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        _log.error(
            "Failed to read or parse JSON cache at %s; falling back to default value.",
            path,
            exc_info=True,
        )
        return default


def save_json(path: Path, payload: Any) -> None:
    """Atomically write `payload` as JSON to `path`.

    Each caller writes to its own sibling temporary file, then `os.replace`s it
    onto the target. Unique temporary names keep concurrent requests for the
    same cache key from deleting or replacing one another's in-flight writes.
    """
    ensure_parent(path)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        _log.error("Atomic JSON write to %s failed; cleaning up %s.", path, tmp_path, exc_info=True)
        raise
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                _log.warning("Could not remove stale tmp file %s.", tmp_path, exc_info=True)
