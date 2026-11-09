"""Cloudflare R2 (S3-Compatible) object storage adapter."""

import os
from typing import Optional
import aioboto3

from config import settings


class R2Reader:
    """Asynchronous client for downloading byte-ranges from Cloudflare R2."""

    def __init__(self) -> None:
        self.session = aioboto3.Session()
        self.endpoint_url: Optional[str] = settings.R2_ENDPOINT_URL
        self.bucket_name: str = settings.R2_BUCKET_NAME
        self.access_key: Optional[str] = settings.R2_ACCESS_KEY_ID
        self.secret_key: Optional[str] = settings.R2_SECRET_ACCESS_KEY

    def is_configured(self) -> bool:
        """Verify whether full R2 credentials are provided."""
        return bool(self.endpoint_url and self.access_key and self.secret_key)

    async def get_byte_range(self, chunk_key: str, offset: int, length: int) -> bytes:
        """Download exact byte range of a compressed document chunk at $0 egress.

        Args:
            chunk_key: The S3 object key (e.g., 'chunk_20261109.zst').
            offset: The starting byte offset in the chunk.
            length: The number of bytes to read.

        Returns:
            The raw bytes within the specified range.
        """
        if not self.is_configured():
            local_path = os.path.join("data", "chunks", chunk_key)
            if os.path.exists(local_path):
                with open(local_path, "rb") as file_handle:
                    file_handle.seek(offset)
                    return file_handle.read(length)
            return b""

        range_header = f"bytes={offset}-{offset + length - 1}"
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name="auto",
        ) as s3_client:
            response = await s3_client.get_object(
                Bucket=self.bucket_name,
                Key=chunk_key,
                Range=range_header,
            )
            async with response["Body"] as stream:
                return await stream.read()


r2_reader = R2Reader()
