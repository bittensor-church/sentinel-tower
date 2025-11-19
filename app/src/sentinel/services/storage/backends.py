"""Backend strategy implementations for data persistence."""

from pathlib import Path


class LocalBackendStrategy:
    """Stores data to local filesystem."""

    def __init__(self, base_path: str | Path, *, create_dirs: bool = True) -> None:
        """
        Initialize local filesystem backend.

        Args:
            base_path: Base directory for storage
            create_dirs: Whether to create directories if they don't exist

        """
        self.base_path = Path(base_path)
        self.create_dirs = create_dirs

    def write(self, data: bytes, path: str) -> str:
        """
        Write data to local filesystem.

        Args:
            data: Data bytes to write
            path: Relative path from base_path

        Returns:
            Absolute path where file was written

        """
        full_path = self.base_path / path

        if self.create_dirs:
            full_path.parent.mkdir(parents=True, exist_ok=True)

        # Append mode for JSONL, write mode for others
        mode = "ab" if full_path.suffix == ".jsonl" else "wb"
        with full_path.open(mode) as f:
            f.write(data)

        return str(full_path.absolute())


class S3BackendStrategy:
    """Stores data to AWS S3."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str | None = None,
    ) -> None:
        """
        Initialize S3 backend.

        Args:
            bucket: S3 bucket name
            prefix: Optional prefix for all keys
            aws_access_key_id: AWS access key (optional, uses default credentials if None)
            aws_secret_access_key: AWS secret key (optional)
            region_name: AWS region (optional)

        """
        self.bucket = bucket
        self.prefix = prefix.rstrip("/")

        try:
            import boto3  # noqa: PLC0415
        except ImportError as e:
            msg = "boto3 is required for S3 backend. Install with: pip install boto3"
            raise ImportError(msg) from e

        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )

    def write(self, data: bytes, path: str) -> str:
        """
        Write data to S3.

        Args:
            data: Data bytes to write
            path: S3 key (relative to prefix)

        Returns:
            S3 URI (s3://bucket/key)

        """
        key = f"{self.prefix}/{path}".lstrip("/")

        self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=data)

        return f"s3://{self.bucket}/{key}"


class InMemoryBackendStrategy:
    """Stores data in memory (useful for testing)."""

    def __init__(self) -> None:
        """Initialize in-memory storage."""
        self.storage: dict[str, bytes] = {}

    def write(self, data: bytes, path: str) -> str:
        """
        Write data to memory.

        Args:
            data: Data bytes to write
            path: Storage key

        Returns:
            Path where data was stored

        """
        self.storage[path] = data
        return f"memory://{path}"

    def read(self, path: str) -> bytes:
        """
        Read data from memory.

        Args:
            path: Storage key

        Returns:
            Stored data bytes

        """
        return self.storage[path]
