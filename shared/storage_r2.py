import os
import io
import aioboto3
from typing import Optional
from shared.config import settings

class R2StorageManager:
    """Async Cloudflare R2 (S3-Compatible) chunked storage adapter."""
    def __init__(self):
        self.session = aioboto3.Session()
        self.endpoint_url = settings.R2_ENDPOINT_URL
        self.bucket_name = settings.R2_BUCKET_NAME
        self.access_key = settings.R2_ACCESS_KEY_ID
        self.secret_key = settings.R2_SECRET_ACCESS_KEY

    def is_configured(self) -> bool:
        return bool(self.endpoint_url and self.access_key and self.secret_key)

    async def put_chunk(self, chunk_key: str, data: bytes) -> bool:
        """Upload a Zstd compressed chunk of pages to Cloudflare R2."""
        if not self.is_configured():
            # In local dev without R2, write to local scratch directory
            os.makedirs("data/chunks", exist_ok=True)
            with open(f"data/chunks/{chunk_key}", "wb") as f:
                f.write(data)
            return True

        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name="auto"
        ) as s3:
            await s3.put_object(
                Bucket=self.bucket_name,
                Key=chunk_key,
                Body=data,
                ContentType="application/octet-stream"
            )
            return True

    async def get_byte_range(self, chunk_key: str, offset: int, length: int) -> bytes:
        """Download exact byte range of a specific document with $0 egress fees."""
        if not self.is_configured():
            local_path = f"data/chunks/{chunk_key}"
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    f.seek(offset)
                    return f.read(length)
            return b""

        range_header = f"bytes={offset}-{offset + length - 1}"
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name="auto"
        ) as s3:
            resp = await s3.get_object(
                Bucket=self.bucket_name,
                Key=chunk_key,
                Range=range_header
            )
            async with resp['Body'] as stream:
                return await stream.read()

r2_storage = R2StorageManager()

