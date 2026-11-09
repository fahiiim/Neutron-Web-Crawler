"""Configuration module for the Search Gateway microservice."""

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Pydantic-based configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "production"
    PORT: int = 7860
    INTERNAL_API_KEY: str = "neutron-secret-internal-key"

    # Turso LibSQL Configuration
    TURSO_DATABASE_URL: str = "libsql://neutron-db-demo.turso.io"
    TURSO_AUTH_TOKEN: str = "turso-token-placeholder"

    # Cloudflare R2 S3 Object Storage Configuration
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "neutron-page-cache"
    R2_ENDPOINT_URL: Optional[str] = None

    # Hugging Face Space URL for the Crawler Worker
    # (e.g. https://yourusername-neutron-crawler.hf.space)
    CRAWLER_SERVICE_URL: str = "http://localhost:7861"


settings = GatewaySettings()
