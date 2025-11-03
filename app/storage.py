import abc
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

try:
    import boto3
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None


class StorageError(Exception):
    pass


class BaseStorage(abc.ABC):
    @abc.abstractmethod
    def save(self, file_obj, destination_path: str) -> str:
        """Persist the incoming file-like object and return its storage key."""

    @abc.abstractmethod
    def delete(self, storage_key: str) -> None:
        """Remove an asset from storage (no-op if missing)."""

    @abc.abstractmethod
    def generate_url(self, storage_key: str, expires_in: int = 3600) -> str:
        """Return a URL that can be used to access the asset."""

    @abc.abstractmethod
    def resolve_path(self, storage_key: str) -> str:
        """Return the absolute filesystem path for a stored asset."""


class LocalStorage(BaseStorage):
    def __init__(self, root_directory: str, public_base_url: Optional[str] = None):
        self.root = root_directory
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None
        os.makedirs(self.root, exist_ok=True)

    def _path(self, storage_key: str) -> str:
        safe_key = storage_key.replace("..", "_")
        return os.path.abspath(os.path.join(self.root, safe_key))

    def save(self, file_obj, destination_path: str) -> str:
        dest_path = self._path(destination_path)
        directory = os.path.dirname(dest_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        file_obj.save(dest_path)
        return destination_path

    def delete(self, storage_key: str) -> None:
        path = self._path(storage_key)
        if os.path.exists(path):
            os.remove(path)

    def generate_url(self, storage_key: str, expires_in: int = 3600) -> str:
        if self.public_base_url:
            expiry = int((datetime.utcnow() + timedelta(seconds=expires_in)).timestamp())
            return f"{self.public_base_url}/{quote(storage_key)}?expires={expiry}"
        return f"/storage/local/{quote(storage_key)}"

    def resolve_path(self, storage_key: str) -> str:
        return self._path(storage_key)


class S3Storage(BaseStorage):
    def __init__(
        self,
        bucket: str,
        *,
        base_path: Optional[str] = None,
        region_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        public_base_url: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        if boto3 is None:
            raise StorageError("boto3 is required for S3 storage")
        if not bucket:
            raise StorageError("AWS_S3_BUCKET must be configured for S3 storage")

        session = boto3.session.Session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )
        self.client = session.client("s3", endpoint_url=endpoint_url)
        self.bucket = bucket
        self.base_path = base_path.strip("/") if base_path else ""
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None

    def _key(self, storage_key: str) -> str:
        clean = storage_key.lstrip("/")
        if self.base_path:
            return f"{self.base_path}/{clean}"
        return clean

    def save(self, file_obj, destination_path: str) -> str:
        key = self._key(destination_path)
        file_obj.stream.seek(0)
        self.client.upload_fileobj(file_obj.stream, self.bucket, key)
        return destination_path

    def delete(self, storage_key: str) -> None:
        key = self._key(storage_key)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey:
            pass

    def generate_url(self, storage_key: str, expires_in: int = 3600) -> str:
        key = self._key(storage_key)
        if self.public_base_url:
            return f"{self.public_base_url}/{quote(key)}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def resolve_path(self, storage_key: str) -> str:
        raise StorageError("S3 storage does not expose local file paths")
