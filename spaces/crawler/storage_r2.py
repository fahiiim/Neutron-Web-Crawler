"""Cloudflare R2 (S3-Compatible) object storage upload adapter."""

import os
from typing import Optional
import aioboto3

from config import settings


class R2Uploader:
    """Asynchronous client for uploading compressed page chunks to Cloudflare R2."""

    def __init__(self) -> None:
        self.session = aioboto3.Session()
        self.endpoint_url: Optional[str] = settings.R2_ENDPOINT_URL
        self.bucket_name: str = settings.R2_BUCKET_NAME
        self.access_key: Optional[str] = settings.R2_ACCESS_KEY_ID
        self.secret_key: Optional[str] = settings.R2_SECRET_ACCESS_KEY

    def is_configured(self) -> bool:
        """Verify whether full R2 credentials are provided."""
        return bool(self.endpoint_url and self.access_key and self.secret_key)

    async def put_chunk(self, chunk_key: str, data: bytes) -> bool:
        """Upload a Zstandard compressed chunk of pages to Cloudflare R2.

        Args:
            chunk_key: The target S3 key (e.g. 'chunk_20261109.zst').
            data: Binary payload to write.

        Returns:
            True if upload succeeds, False otherwise.
        """
        if not self.is_configured():
            os.makedirs(os.path.join("data", "chunks"), exist_ok=True)
            local_path = os.path.join("data", "chunks", chunk_key)
            with open(local_path, "wb") as file_handle:
                file_handle.write(data)
            return True

        try:
            async with self.session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name="auto",
            ) as s3_client:
                await s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=chunk_key,
                    Body=data,
                    ContentType="application/octet-stream",
                )
                return True
        except Exception as exc:
            print(f"[R2 Upload Error]: {exc}")
            return False


r2_uploader = R2Uploader()

