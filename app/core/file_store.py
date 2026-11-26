# File Store — bytes on disk behind a small interface
# ----------------------------------------------------
# Slice 3 stores uploaded files on local disk; S3 can replace the implementation
# later without touching the document service.
#
# `documents.disk_path` holds the store reference returned by `save()`. Disk
# stores a path inside UPLOAD_DIR; future stores may return an opaque key.
#
# Keys are generated server-side (`{org_id}/{doc_id}{suffix}`), never from the
# client filename, so a hostile name cannot escape the upload root.

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

READ_CHUNK = 1024 * 1024


class FileStoreError(RuntimeError):
    """Base class for storage failures."""


class FileTooLargeError(FileStoreError):
    """Upload exceeded the configured byte limit."""


class EmptyFileError(FileStoreError):
    """Upload contained zero bytes."""


class FileNotFoundInStoreError(FileStoreError):
    """The stored reference no longer exists on the backing store."""


@dataclass(frozen=True)
class StoredFile:
    key: str
    path: str
    size: int


class FileStore(Protocol):
    def save(self, key: str, source: BinaryIO, *, max_bytes: int) -> StoredFile: ...

    def read(self, ref: str) -> bytes: ...

    def local_path(self, ref: str) -> Path:
        """A path the parser can read. Remote stores would materialize a temp file."""
        ...

    def exists(self, ref: str) -> bool: ...

    def delete(self, ref: str) -> None: ...


class DiskFileStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _target(self, key: str) -> Path:
        target = (self.root / key).resolve()
        root = self.root.resolve()
        if root != target and root not in target.parents:
            raise FileStoreError(f"Invalid storage key: {key!r}")
        return target

    def save(self, key: str, source: BinaryIO, *, max_bytes: int) -> StoredFile:
        target = self._target(key)
        target.parent.mkdir(parents=True, exist_ok=True)

        size = 0
        try:
            with target.open("wb") as out:
                while True:
                    piece = source.read(READ_CHUNK)
                    if not piece:
                        break
                    size += len(piece)
                    if size > max_bytes:
                        raise FileTooLargeError(
                            f"File exceeds {max_bytes // (1024 * 1024)}MB limit"
                        )
                    out.write(piece)
        except Exception:
            target.unlink(missing_ok=True)
            raise

        if size == 0:
            target.unlink(missing_ok=True)
            raise EmptyFileError("Uploaded file is empty")
        return StoredFile(key=key, path=str(target), size=size)

    def _path(self, ref: str) -> Path:
        path = Path(ref)
        return path if path.is_absolute() else self.root / path

    def read(self, ref: str) -> bytes:
        path = self._path(ref)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise FileNotFoundInStoreError(f"File missing from disk: {path}") from exc

    def local_path(self, ref: str) -> Path:
        path = self._path(ref)
        if not path.exists():
            raise FileNotFoundInStoreError(f"File missing from disk: {path}")
        return path

    def exists(self, ref: str) -> bool:
        return self._path(ref).exists()

    def delete(self, ref: str) -> None:
        path = self._path(ref)
        try:
            path.unlink(missing_ok=True)
        except IsADirectoryError:
            shutil.rmtree(path, ignore_errors=True)


def get_file_store() -> FileStore:
    """Build the configured store. Read settings at call time so tests can override."""
    from app.core.config import settings

    return DiskFileStore(settings.UPLOAD_DIR)
