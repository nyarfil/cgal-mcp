"""Opt-in operation result cache: validated outputs only, integrity-checked, bounded.

An entry is written only after every mandatory validator of the producing job passed. The
key binds the operation id and revision, normalized parameters, kernel, input content hashes
(with type/unit/format), the registry revision and the native worker executable digest, so a
registry or worker change can never hit an old entry. Each entry carries an HMAC over its
body (per-cache random secret) and every output blob is re-hashed on read; any mismatch,
unreadable file or schema drift is a miss and the entry is deleted. A hit only replaces the
transform execution: the runtime still runs every mandatory validator live on the cached
candidate before anything is published, and records the stored verdicts for comparison.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Any

from .util import canonical_json, digest_file

CACHE_FORMAT = 1


class ResultCache:
    def __init__(self, root: Path, *, registry_revision: str, max_entries: int = 256,
                 max_bytes: int = 1 << 30):
        if not (1 <= max_entries <= 1_000_000 and 1 <= max_bytes <= 1 << 44):
            raise ValueError("Result cache bounds are invalid")
        self.root = root.resolve()
        self.entries = self.root / "entries"
        self.blobs = self.root / "blobs"
        for directory in (self.root, self.entries, self.blobs):
            directory.mkdir(parents=True, exist_ok=True)
        secret_path = self.root / "secret.key"
        if not secret_path.is_file() or secret_path.stat().st_size != 32:
            secret_path.write_bytes(secrets.token_bytes(32))
        self._secret = secret_path.read_bytes()
        self.registry_revision = registry_revision
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.stats = {"hits": 0, "misses": 0, "stores": 0, "rejected_tampered": 0,
                      "rejected_stale": 0, "evicted": 0}
        self._prune_stale()

    # ------------------------------------------------------------------ keys and integrity

    def key(self, *, operation: dict[str, Any], step: dict[str, Any], inputs: list[dict[str, Any]],
            worker_sha256: str, cgal_version: Any) -> str:
        material = {"cache_format": CACHE_FORMAT, "operation": operation["id"],
                    "revision": operation["revision"], "registry_revision": self.registry_revision,
                    "worker_sha256": worker_sha256, "cgal_version": cgal_version,
                    "kernel": step["kernel"], "parameters": step["parameters"],
                    "inputs": [{"type": item["type"], "unit": item["unit"], "format": item["format"],
                                "sha256": item["sha256"]} for item in inputs]}
        return hashlib.sha256(canonical_json(material)).hexdigest()

    def _mac(self, body: dict[str, Any]) -> str:
        return hmac.new(self._secret, canonical_json(body), hashlib.sha256).hexdigest()

    def _entry_path(self, key: str) -> Path:
        return self.entries / f"{key}.json"

    def discard(self, key: str) -> None:
        self._drop(key)
        self._collect_blobs()

    def _drop(self, key: str) -> None:
        try:
            self._entry_path(key).unlink()
        except OSError:
            pass

    def _read(self, key: str) -> dict[str, Any] | None:
        path = self._entry_path(key)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            body, mac = entry["body"], entry["mac"]
            if not isinstance(body, dict) or not hmac.compare_digest(str(mac), self._mac(body)):
                raise ValueError("mac")
            if body.get("key") != key or body.get("cache_format") != CACHE_FORMAT:
                raise ValueError("identity")
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            self.stats["rejected_tampered"] += 1
            self._drop(key)
            return None
        if body.get("registry_revision") != self.registry_revision:
            self.stats["rejected_stale"] += 1
            self._drop(key)
            return None
        return body

    # ------------------------------------------------------------------ lookup / store

    def lookup(self, key: str, worker_sha256: str, destination: Path) -> dict[str, Any] | None:
        """Copy a verified entry's outputs into ``destination``; None on any doubt (miss)."""
        body = self._read(key)
        if body is None or body.get("worker_sha256") != worker_sha256:
            if body is not None:
                self.stats["rejected_stale"] += 1
                self._drop(key)
            self.stats["misses"] += 1
            return None
        copied: list[Path] = []
        try:
            for item in body["outputs"]:
                name = Path(item["filename"]).name
                if name != item["filename"] or not name:
                    raise ValueError("filename")
                blob = self.blobs / item["sha256"]
                target = destination / name
                shutil.copyfile(blob, target)
                copied.append(target)
                if digest_file(target) != item["sha256"] or target.stat().st_size != item["size"]:
                    raise ValueError("blob digest")
        except (OSError, ValueError, KeyError, TypeError):
            for path in copied:
                path.unlink(missing_ok=True)
            self.stats["rejected_tampered"] += 1
            self.stats["misses"] += 1
            self._drop(key)
            return None
        os.utime(self._entry_path(key))  # LRU recency
        self.stats["hits"] += 1
        return body

    def store(self, key: str, *, worker_sha256: str, operation: str, outputs: list[dict[str, Any]],
              metrics: Any, diagnostics: Any, verdicts: list[dict[str, Any]]) -> None:
        """Record a transform result whose mandatory validators all passed in this job."""
        records = []
        for item in outputs:
            source = Path(item["path"])
            digest = digest_file(source)
            blob = self.blobs / digest
            if not blob.is_file() or digest_file(blob) != digest:
                temporary = self.blobs / f".{digest}.{secrets.token_hex(4)}.tmp"
                shutil.copyfile(source, temporary)
                os.replace(temporary, blob)
            records.append({"slot": item["slot"], "type": item["type"], "format": item["format"],
                            "unit": item["unit"], "filename": source.name, "sha256": digest,
                            "size": source.stat().st_size})
        body = {"cache_format": CACHE_FORMAT, "key": key, "operation": operation,
                "registry_revision": self.registry_revision, "worker_sha256": worker_sha256,
                "outputs": records, "metrics": metrics, "diagnostics": diagnostics,
                "validator_verdicts": verdicts}
        temporary = self.entries / f".{key}.{secrets.token_hex(4)}.tmp"
        temporary.write_text(json.dumps({"body": body, "mac": self._mac(body)}, sort_keys=True),
                             encoding="utf-8")
        os.replace(temporary, self._entry_path(key))
        self.stats["stores"] += 1
        self._evict()

    # ------------------------------------------------------------------ bounds

    def _prune_stale(self) -> None:
        for path in list(self.entries.glob("*.json")):
            self._read(path.stem)
        for path in self.entries.glob(".*.tmp"):
            path.unlink(missing_ok=True)
        self._collect_blobs()

    def _collect_blobs(self) -> None:
        referenced: set[str] = set()
        for path in self.entries.glob("*.json"):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))["body"]
                referenced.update(item["sha256"] for item in body["outputs"])
            except (OSError, ValueError, KeyError, TypeError):
                path.unlink(missing_ok=True)
        for blob in self.blobs.iterdir():
            if blob.name not in referenced:
                blob.unlink(missing_ok=True)

    def usage(self) -> tuple[int, int]:
        entries = list(self.entries.glob("*.json"))
        size = sum(blob.stat().st_size for blob in self.blobs.iterdir() if blob.is_file())
        return len(entries), size

    def _evict(self) -> None:
        entries = sorted(self.entries.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        count, size = self.usage()
        while entries and (count > self.max_entries or size > self.max_bytes):
            entries.pop(0).unlink(missing_ok=True)
            self.stats["evicted"] += 1
            self._collect_blobs()
            count, size = self.usage()

    def clear(self) -> None:
        for path in self.entries.glob("*.json"):
            path.unlink(missing_ok=True)
        self._collect_blobs()

    def status(self) -> dict[str, Any]:
        count, size = self.usage()
        return {"enabled": True, "cache_format": CACHE_FORMAT, "entries": count, "bytes": size,
                "max_entries": self.max_entries, "max_bytes": self.max_bytes, **self.stats}
