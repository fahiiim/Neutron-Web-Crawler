"""Configuration module for the Crawler Worker microservice."""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class CrawlerSettings(BaseSettings):
    """Pydantic-based configuration for the crawler worker."""

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

    # Hugging Face Space URL for the Stealth Renderer
    # (e.g. https://yourusername-neutron-renderer.hf.space)
    RENDERER_SERVICE_URL: str = "http://localhost:7862"

    # Crawler Tuning & Politeness
    BACKGROUND_CRAWLER_ENABLED: bool = True
    MAX_CONCURRENT_JIT_FETCHES: int = 12
    DEFAULT_CRAWL_DELAY_MS: int = 1500
    BACKGROUND_FETCH_INTERVAL_SECONDS: float = 3.1  # ~27,400 pages/day


settings = CrawlerSettings()
