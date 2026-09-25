"""Object storage for generated frames.

Keys are content-addressed: identical parameters produce identical bytes, so the
hash is the key. That gives free dedupe and makes an immutable cache header
honest.

Two backends behind one Protocol. `get_storage()` raises at import time when the
configured backend cannot actually work -- a config value that names a backend we
silently ignore is worse than a crash, because frames would be written to
container-local disk and vanish on the next deploy with nothing in the logs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import get_settings

_MAGIC: dict[bytes, str] = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"RIFF": "webp",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}

MAX_BYTES = 12 * 1024 * 1024
MAX_DIMENSION = 4096


class UnsupportedImageError(ValueError):
    pass


class StorageMisconfiguredError(RuntimeError):
    """The configured backend cannot work with the settings provided."""


def sniff(data: bytes) -> str:
    """Verify magic bytes. A declared content type is never trusted."""
    if len(data) > MAX_BYTES:
        raise UnsupportedImageError(f"image is larger than {MAX_BYTES} bytes")
    if len(data) < 16:
        raise UnsupportedImageError("response is too short to be an image")
    for magic, ext in _MAGIC.items():
        if data.startswith(magic):
            if ext == "webp" and data[8:12] != b"WEBP":
                continue
            return ext
    raise UnsupportedImageError("bytes are not a supported image format")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_for(digest: str, ext: str) -> str:
    # Two-character prefix keeps directory and bucket listings sane at volume.
    return f"frames/{digest[:2]}/{digest}.{ext}"


def content_type(key: str) -> str:
    return _CONTENT_TYPES.get(key.rsplit(".", 1)[-1], "application/octet-stream")


@runtime_checkable
class Storage(Protocol):
    def exists(self, key: str) -> bool: ...
    def put(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    @staticmethod
    def content_type(key: str) -> str: ...


class LocalStorage:
    """Filesystem backend. Development, and single-node deployments."""

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root or get_settings().storage_local_dir)

    def _path(self, key: str) -> Path:
        # Keys are server-generated hex digests, but resolve anyway: a path
        # traversal here would read arbitrary files off the host.
        p = (self._root / key).resolve()
        root = self._root.resolve()
        if not p.is_relative_to(root):
            raise ValueError(f"storage key escapes the root: {key!r}")
        return p

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a reader never sees a partial file.
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    @staticmethod
    def content_type(key: str) -> str:
        return content_type(key)


class S3Storage:
    """S3-compatible backend (AWS S3, R2, Vercel Blob via the S3 API).

    Synchronous on purpose: callers run it through `anyio.to_thread`, which is
    what keeps the event loop free. boto3 is an optional extra, so a deployment
    that does not use S3 does not carry it.
    """

    def __init__(self) -> None:
        s = get_settings()
        if not s.s3_bucket:
            raise StorageMisconfiguredError(
                "STORAGE_BACKEND=s3 requires S3_BUCKET to be set."
            )
        try:
            import boto3
        except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
            raise StorageMisconfiguredError(
                'STORAGE_BACKEND=s3 needs the s3 extra: pip install -e "api[s3]"'
            ) from exc

        self._bucket = s.s3_bucket
        self._client = boto3.client(
            "s3",
            region_name=s.s3_region or None,
            endpoint_url=s.s3_endpoint_url or None,
        )

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type(key),
            CacheControl="public, max-age=31536000, immutable",
        )

    def read(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = obj["Body"].read()
        return body

    @staticmethod
    def content_type(key: str) -> str:
        return content_type(key)


_cached: Storage | None = None


def get_storage() -> Storage:
    """Resolve the configured backend, or fail loudly.

    Never silently falls back to local: that is how frames end up on a container
    filesystem in production and disappear on redeploy.
    """
    global _cached
    if _cached is not None:
        return _cached
    backend = get_settings().storage_backend
    if backend == "local":
        _cached = LocalStorage()
    elif backend == "s3":
        _cached = S3Storage()
    else:  # pragma: no cover - Literal makes this unreachable
        raise StorageMisconfiguredError(f"unknown STORAGE_BACKEND {backend!r}")
    return _cached


def reset_storage_cache() -> None:
    """For tests that switch backends."""
    global _cached
    _cached = None
