"""Small standard-library helpers: canonical JSON, hashes, atomic writes."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def canonical_json(obj) -> str:
    """Canonical serialization used for every hash in this package."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scene_bytes(scene: dict) -> bytes:
    return (canonical_json(scene) + "\n").encode("utf-8")


def manifest_bytes(manifest: dict) -> bytes:
    return (canonical_json(manifest) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def deep_copy(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False))


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write(path: Path, data: bytes) -> None:
    """Write bytes, fsync, then os.replace (atomic on the same filesystem)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def atomic_write_json(path: Path, obj) -> None:
    atomic_write(path, (canonical_json(obj) + "\n").encode("utf-8"))


def get_path(obj, path: str):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def set_path(obj, path: str, value) -> None:
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def delete_path(obj, path: str) -> None:
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    if isinstance(cur, list):
        del cur[int(parts[-1])]
    else:
        cur.pop(parts[-1], None)
