"""Shared Pydantic settings for Leapcell-ready Neutron microservices."""

from __future__ import annotations

from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_KEY_PLACEHOLDERS = {
    "neutron-secret-internal-key",
    "your_64_character_hex_secret",
    "change_me",
    "change_me_to_a_random_secret",
}


class ServiceBaseSettings(BaseSettings):
    """Common configuration shared across Neutron microservices."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "production"
    PORT: int = 8080
    INTERNAL_API_KEY: str = ""
    REQUIRE_INTERNAL_API_KEY: bool = False

    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""

    CORS_ALLOW_ORIGINS: str = "*"

    @field_validator("INTERNAL_API_KEY")
    @classmethod
    def validate_internal_api_key(cls, value: str) -> str:
        """Reject well-known hardcoded placeholder secrets."""
        cleaned = (value or "").strip()
        if cleaned.lower() in _INSECURE_KEY_PLACEHOLDERS:
            raise ValueError(
                "INTERNAL_API_KEY must not use a hardcoded placeholder secret."
            )
        return cleaned

    def cors_origins_list(self) -> List[str]:
        """Parse comma-separated CORS origins cleanly."""
        raw = [o.strip() for o in (self.CORS_ALLOW_ORIGINS or "").split(",") if o.strip()]
        return raw or ["*"]


class GatewayServiceSettings(ServiceBaseSettings):
    """Configuration for the public Edge Gateway microservice."""

    SEARCH_SERVICE_URL: str = "http://127.0.0.1:8081"
    CRAWLER_SERVICE_URL: str = "http://127.0.0.1:8082"
    RPC_PROTOCOL: str = "connect"  # connect | grpc_web | grpc
    RPC_TIMEOUT_MS: int = 55000  # Accommodates Render/PaaS free-tier cold starts (~30-50s)
    JIT_CACHE_THRESHOLD: int = 5
    SYNTHESIS_MAX_SOURCES: int = 5
    LIVE_JIT_DEADLINE_SECONDS: float = 4.8

    RATE_LIMIT_SEARCH: str = "30/minute"
    RATE_LIMIT_STREAM: str = "15/minute"
    RATE_LIMIT_RESEARCH: str = "20/minute"


class SearchServiceSettings(ServiceBaseSettings):
    """Configuration for the Index Query & Synthesis microservice."""

    SYNTHESIS_MAX_SOURCES: int = 5


class CrawlerServiceSettings(ServiceBaseSettings):
    """Configuration for the On-Demand Discovery & Crawler microservice."""

    BACKGROUND_CRAWLER_ENABLED: bool = False  # Serverless-safe default
    MAX_CONCURRENT_JIT_FETCHES: int = 12
    LIVE_MAX_RETRIES: int = 1
    LIVE_FETCH_TIMEOUT_SECONDS: float = 3.0
    LIVE_JIT_DEADLINE_SECONDS: float = 4.8
    FETCH_TIMEOUT_SECONDS: float = 6.0
    WAF_COOLDOWN_SECONDS: int = 86400
    BLOOM_CAPACITY: int = 1_000_000
    BLOOM_FP_RATE: float = 0.001
    BRAVE_SEARCH_API_KEY: str = ""

