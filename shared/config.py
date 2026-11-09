import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class SharedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    ENVIRONMENT: str = "production"
    INTERNAL_API_KEY: str = "neutron-internal-secret-change-me"

    # Turso LibSQL Database
    TURSO_DATABASE_URL: str = "libsql://neutron-db-demo.turso.io"
    TURSO_AUTH_TOKEN: str = "turso-auth-token-placeholder"

    # Cloudflare R2 Object Storage
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "neutron-page-cache"
    R2_ENDPOINT_URL: Optional[str] = None

    # Microservice Internal Cluster URLs (K8s Service Discovery DNS)
    GATEWAY_SERVICE_URL: str = "http://svc-search-gateway.neutron.svc.cluster.local:8000"
    CRAWLER_SERVICE_URL: str = "http://svc-crawler-worker.neutron.svc.cluster.local:8001"
    RENDERER_SERVICE_URL: str = "http://svc-stealth-renderer.neutron.svc.cluster.local:8002"

    # Crawler Tuning
    MAX_CONCURRENT_JIT_FETCHES: int = 12
    DEFAULT_CRAWL_DELAY_MS: int = 1500
    BACKGROUND_CRAWLER_ENABLED: bool = True

settings = SharedSettings()

