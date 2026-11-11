"""Configuration module for the Crawler Worker microservice."""

from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_KEY_PLACEHOLDERS = {
    "neutron-secret-internal-key",
    "your_64_character_hex_secret",
    "change_me",
    "change_me_to_a_random_secret",
}


class CrawlerSettings(BaseSettings):
    """Pydantic-based configuration for the crawler worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "production"
    PORT: int = 7860
    INTERNAL_API_KEY: str = ""
    REQUIRE_INTERNAL_API_KEY: bool = False

    # Turso LibSQL Configuration
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""

    # Cloudflare R2 S3 Object Storage Configuration (Optional)
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "neutron-page-cache"
    R2_ENDPOINT_URL: Optional[str] = None

    # Hugging Face Space URL for the Stealth Renderer
    RENDERER_SERVICE_URL: str = ""

    # Optional External Discovery Keys
    BRAVE_SEARCH_API_KEY: Optional[str] = None

    # Crawler Tuning & Politeness
    BACKGROUND_CRAWLER_ENABLED: bool = True
    MAX_CONCURRENT_JIT_FETCHES: int = 12
    DEFAULT_CRAWL_DELAY_MS: int = 1500
    BACKGROUND_FETCH_INTERVAL_SECONDS: float = 3.1  # ~27,400 pages/day
    JIT_CACHE_THRESHOLD: int = 5
    MAX_RETRY_ATTEMPTS: int = 3
    FETCH_TIMEOUT_SECONDS: float = 6.0
    LIVE_MAX_RETRIES: int = 1
    LIVE_FETCH_TIMEOUT_SECONDS: float = 3.0
    LIVE_JIT_DEADLINE_SECONDS: float = 4.8
    LIVE_RENDER_TIMEOUT_SECONDS: float = 4.5
    WAF_COOLDOWN_SECONDS: int = 86400
    SYNTHESIS_MAX_SOURCES: int = 5
    SIMHASH_HAMMING_THRESHOLD: int = 3
    FRESHNESS_TTL_DAYS: int = 7

    # Rate limit for /api/research endpoint
    RATE_LIMIT_RESEARCH: str = "20/minute"

    # Bloom Filter Configuration
    BLOOM_CAPACITY: int = 1_000_000
    BLOOM_FP_RATE: float = 0.001

    # Public Endpoint Rate Limits
    RATE_LIMIT_SEARCH: str = "30/minute"
    RATE_LIMIT_STREAM: str = "15/minute"

    @field_validator("INTERNAL_API_KEY")
    @classmethod
    def validate_internal_api_key(cls, value: str) -> str:
        """Reject well-known hardcoded placeholder secrets."""
        cleaned = (value or "").strip()
        if cleaned.lower() in _INSECURE_KEY_PLACEHOLDERS:
            raise ValueError(
                "INTERNAL_API_KEY must not use an insecure placeholder value. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return cleaned


settings = CrawlerSettings()
