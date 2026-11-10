"""Configuration module for the Stealth Renderer microservice."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_KEY_PLACEHOLDERS = {
    "neutron-secret-internal-key",
    "your_64_character_hex_secret",
    "change_me",
    "change_me_to_a_random_secret",
}


class RendererSettings(BaseSettings):
    """Pydantic-based configuration for the renderer."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "production"
    PORT: int = 7860
    INTERNAL_API_KEY: str = ""
    MAX_CONCURRENT_RENDERS: int = 4
    RENDER_TIMEOUT_MS: int = 8500

    @field_validator("INTERNAL_API_KEY")
    @classmethod
    def validate_internal_api_key(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if cleaned.lower() in _INSECURE_KEY_PLACEHOLDERS:
            raise ValueError(
                "INTERNAL_API_KEY must not use a hardcoded placeholder value."
            )
        return cleaned


settings = RendererSettings()
