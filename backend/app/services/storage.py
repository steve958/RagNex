from __future__ import annotations

import mimetypes
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
import anyio
from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error

from backend.app.core.config import settings
from backend.app.core.validation import safe_filename
from backend.app.services.parsing import SUPPORTED_EXTENSIONS


# Only formats the parser handles (single source of truth in services/parsing.py).
DEFAULT_ALLOWED_EXTENSIONS = SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class StorageObjectRef:
    bucket: str
    object_key: str


class StorageService:
    def __init__(self) -> None:
        endpoint = settings.s3_endpoint_url
        # An https:// endpoint means TLS even if S3_SECURE wasn't set; dropping the scheme
        # alone would silently connect without it.
        secure = settings.s3_secure or endpoint.startswith("https://")
        # Minio client wants host:port without scheme
        endpoint = endpoint.replace("https://", "").replace("http://", "")

        self._client = Minio(
            endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=secure,
            region=settings.s3_region,
        )

    @staticmethod
    def bucket_for_tenant(tenant_id: uuid.UUID) -> str:
        # Must be lowercase, <=63 chars, alnum+hyphen
        return f"tenant-{tenant_id.hex}".lower()[:63]

    def _ensure_bucket_sync(self, bucket: str) -> None:
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    async def ensure_bucket(self, tenant_id: uuid.UUID) -> str:
        bucket = self.bucket_for_tenant(tenant_id)
        await anyio.to_thread.run_sync(lambda: self._ensure_bucket_sync(bucket))
        return bucket

    @staticmethod
    def validate_file_type(filename: str, content_type: str | None = None) -> None:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in DEFAULT_ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {ext}")

        # Best-effort MIME validation if provided.
        if content_type:
            guessed, _ = mimetypes.guess_type(filename)
            if guessed and not content_type.startswith(guessed.split("/")[0]):
                # Only check top-level type (e.g. application/*)
                # to avoid false positives.
                pass

    @staticmethod
    def _object_key(filename: str) -> str:
        # safe_filename drops path components for both / and \ (os.path.basename only
        # handles the platform's own separator) and control characters.
        return f"{uuid.uuid4().hex}/{safe_filename(filename)}"

    async def upload_file(self, tenant_id: uuid.UUID, file: UploadFile) -> str:
        """Upload a file into the tenant bucket.

        Returns the object_key.
        """

        self.validate_file_type(file.filename or "", file.content_type)

        bucket = await self.ensure_bucket(tenant_id)
        object_key = self._object_key(file.filename or "upload")

        # UploadFile.file is a SpooledTemporaryFile; stream it with multipart when size unknown.
        def put_sync() -> None:
            file.file.seek(0)
            self._client.put_object(
                bucket_name=bucket,
                object_name=object_key,
                data=file.file,  # type: ignore[arg-type]
                length=-1,
                part_size=10 * 1024 * 1024,  # 10MB parts
                content_type=file.content_type or "application/octet-stream",
            )

        await anyio.to_thread.run_sync(put_sync)
        return object_key

    async def download_file(self, tenant_id: uuid.UUID, object_key: str) -> bytes:
        bucket = self.bucket_for_tenant(tenant_id)

        def get_sync() -> bytes:
            resp = self._client.get_object(bucket, object_key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await anyio.to_thread.run_sync(get_sync)

    async def file_exists(self, tenant_id: uuid.UUID, object_key: str) -> bool:
        bucket = self.bucket_for_tenant(tenant_id)

        def stat_sync() -> bool:
            try:
                self._client.stat_object(bucket, object_key)
                return True
            except S3Error as e:
                if e.code in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                    return False
                raise

        return await anyio.to_thread.run_sync(stat_sync)

    async def delete_file(self, tenant_id: uuid.UUID, object_key: str) -> None:
        bucket = self.bucket_for_tenant(tenant_id)
        await anyio.to_thread.run_sync(lambda: self._client.remove_object(bucket, object_key))

    async def stream_file(
        self, tenant_id: uuid.UUID, object_key: str, chunk_size: int = 256 * 1024
    ) -> tuple[int | None, Iterator[bytes]]:
        """Open a stored file for streaming: (size in bytes if known, chunks).

        Raises minio.error.S3Error (code NoSuchKey) if the file isn't stored.
        """
        bucket = self.bucket_for_tenant(tenant_id)
        resp = await anyio.to_thread.run_sync(lambda: self._client.get_object(bucket, object_key))
        length = resp.headers.get("Content-Length")

        def chunks() -> Iterator[bytes]:
            try:
                yield from resp.stream(chunk_size)
            finally:
                resp.close()
                resp.release_conn()

        return (int(length) if length else None), chunks()
