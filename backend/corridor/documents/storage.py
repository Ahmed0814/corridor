"""Document storage adapters (security-model.md §8, DECISIONS D-022, D-070).

``LocalStorage`` (development/test) keeps files under DOCUMENT_STORAGE_DIR; ``S3Storage`` is the
production adapter (versioned, SSE-KMS bucket, tenant-prefixed keys, pre-signed URLs) and needs AWS
credentials (Phase 7). Keys always start with ``tenants/<tenant_id>/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from django.conf import settings


class StorageNotConfigured(RuntimeError):
    pass


class DocumentStorage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:  # no "../" escapes
            raise ValueError("invalid storage key")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class S3Storage:
    def put(self, key: str, data: bytes) -> None:
        raise StorageNotConfigured("S3 document storage needs AWS credentials and a bucket (Phase 7).")

    def get(self, key: str) -> bytes:
        raise StorageNotConfigured("S3 document storage needs AWS credentials and a bucket (Phase 7).")


def get_storage() -> DocumentStorage:
    if settings.DOCUMENT_STORAGE_BACKEND == "local":
        return LocalStorage(Path(settings.DOCUMENT_STORAGE_DIR))
    if settings.DOCUMENT_STORAGE_BACKEND == "s3":
        return S3Storage()
    raise StorageNotConfigured(f"unknown DOCUMENT_STORAGE_BACKEND {settings.DOCUMENT_STORAGE_BACKEND!r}")
