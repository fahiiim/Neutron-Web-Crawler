"""Configuration module for the Search Gateway microservice."""

from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_KEY_PLACEHOLDERS = {
    "neutron-secret-internal-key",
    "your_64_character_hex_secret",
    "change_me",
    "change_me_to_a_random_secret",
}


class GatewaySettings(BaseSettings):
    """Pydantic-based configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "production"
    PORT: int = 7860
    INTERNAL_API_KEY: str = ""

    # Turso LibSQL Configuration
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""

    # Cloudflare R2 S3 Object Storage Configuration (Optional)
    R2_ACCOUNT_ID: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "neutron-page-cache"
    R2_ENDPOINT_URL: Optional[str] = None

    # Crawler Worker Service URL
    CRAWLER_SERVICE_URL: str = "http://localhost:7861"
    JIT_CACHE_THRESHOLD: int = 5
    RATE_LIMIT_SEARCH: str = "30/minute"
    RATE_LIMIT_STREAM: str = "15/minute"

    @field_validator("INTERNAL_API_KEY")
    @classmethod
    def validate_internal_api_key(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if cleaned.lower() in _INSECURE_KEY_PLACEHOLDERS:
            raise ValueError(
                "INTERNAL_API_KEY must not use a hardcoded placeholder value."
            )
        return cleaned


settings = GatewaySettings()
