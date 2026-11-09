"""Configuration module for the Stealth Renderer microservice."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class RendererSettings(BaseSettings):
    """Pydantic-based configuration for the renderer."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "production"
    PORT: int = 7860
    INTERNAL_API_KEY: str = "neutron-secret-internal-key"


settings = RendererSettings()
