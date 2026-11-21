"""GPS archive storage for retention (MASTER_PROMPT §2: raw events kept 12 months, then archived to S3).

``LocalDirArchive`` (development/test) writes gzip JSON-lines plus a manifest with the row count and
SHA-256. ``S3Archive`` is the production adapter; it needs AWS credentials and a bucket, so it is an
interface here and listed under "Needs credentials" until Phase 7 (MASTER_PROMPT §0.5).
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from django.conf import settings


@dataclass(frozen=True)
class ArchiveReceipt:
    location: str
    rows: int
    sha256: str


class GpsArchive(Protocol):
    def write(self, partition: str, rows: list[dict[str, Any]]) -> ArchiveReceipt: ...

    def verify(self, receipt: ArchiveReceipt) -> bool: ...


class ArchiveNotConfigured(RuntimeError):
    pass


def _encode(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows).encode()


class LocalDirArchive:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(self, partition: str, rows: list[dict[str, Any]]) -> ArchiveReceipt:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = _encode(rows)
        digest = hashlib.sha256(payload).hexdigest()
        data_path = self.directory / f"{partition}.jsonl.gz"
        with gzip.open(data_path, "wb") as fh:
            fh.write(payload)
        manifest = {"partition": partition, "rows": len(rows), "sha256": digest, "file": data_path.name}
        (self.directory / f"{partition}.manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return ArchiveReceipt(location=str(data_path), rows=len(rows), sha256=digest)

    def verify(self, receipt: ArchiveReceipt) -> bool:
        """Re-read the archive and check both the row count and the checksum before any drop."""
        try:
            with gzip.open(receipt.location, "rb") as fh:
                payload = fh.read()
        except OSError:
            return False
        return hashlib.sha256(payload).hexdigest() == receipt.sha256 and payload.count(b"\n") == receipt.rows


class S3Archive:
    """Production adapter (Phase 7): versioned, encrypted bucket, tenant-agnostic monthly objects."""

    def write(self, partition: str, rows: list[dict[str, Any]]) -> ArchiveReceipt:
        raise ArchiveNotConfigured("S3 GPS archive needs AWS credentials and a bucket (Phase 7).")

    def verify(self, receipt: ArchiveReceipt) -> bool:
        raise ArchiveNotConfigured("S3 GPS archive needs AWS credentials and a bucket (Phase 7).")


def get_archive() -> GpsArchive:
    backend = settings.GPS_ARCHIVE_BACKEND
    if backend == "local":
        return LocalDirArchive(Path(settings.GPS_ARCHIVE_DIR))
    if backend == "s3":
        return S3Archive()
    raise ArchiveNotConfigured(f"unknown GPS_ARCHIVE_BACKEND {backend!r}")
