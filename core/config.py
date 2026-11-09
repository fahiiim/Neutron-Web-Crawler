import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    ENVIRONMENT: str = "development"
    PORT: int = 8000
    INTERNAL_API_KEY: str = "dev_secret_key_change_me"

    # Database Backend: 'turso' or 'supabase'
    DATABASE_BACKEND: str = "turso"

    # Turso / LibSQL Settings
    TURSO_DATABASE_URL: Optional[str] = None
    TURSO_AUTH_TOKEN: Optional[str] = None

    # Supabase / PostgreSQL Settings
    SUPA_CONTROL_DB_URL: Optional[str] = None
    FEDERATED_SHARDS: Optional[str] = None  # Format: "1|uri|rest|key,2|uri|rest|key"

    # Cloudflare R2 / S3 Storage
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "neutron-page-cache"
    R2_ENDPOINT_URL: Optional[str] = None

    # Crawler & Politeness Policies
    MAX_CONCURRENT_JIT_FETCHES: int = 12
    DEFAULT_CRAWL_DELAY_MS: int = 1500
    SHARD_CAPACITY_LIMIT_MB: float = 450.0
    BACKGROUND_CRAWLER_ENABLED: bool = True
    MAX_PAGES_PER_DAY: int = 27400

settings = Settings()

