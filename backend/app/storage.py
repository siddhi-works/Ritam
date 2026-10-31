"""Content-addressed raw file store (local disk now; S3-compatible later behind the same API)."""

import asyncio
import hashlib
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalStore:
    def __init__(self, root: str | Path):
        self._root = Path(root)

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
            raise ValueError("invalid digest")
        return self._root / digest[:2] / digest

    async def put(self, data: bytes) -> tuple[str, str]:
        """Store bytes; returns (sha256, relative path). Idempotent."""
        digest = sha256(data)
        path = self._path(digest)
        if not path.exists():
            await asyncio.to_thread(self._write, path, data)
        return digest, str(path.relative_to(self._root).as_posix())

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    async def get(self, digest: str) -> bytes:
        return await asyncio.to_thread(self._path(digest).read_bytes)
