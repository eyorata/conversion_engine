from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: str = "dev"
    LOG_LEVEL: str = "INFO"
    PORT: int = 8080

    OPENROUTER_API_KEY: Optional[str] = None
    DEV_MODEL: str = "qwen/qwen3-next-80b-a3b"

    ANTHROPIC_API_KEY: Optional[str] = None
    EVAL_MODEL: str = "claude-sonnet-4-6"

    AT_USERNAME: str = "sandbox"
    AT_API_KEY: Optional[str] = None
    AT_SHORTCODE: Optional[str] = None
    AT_WEBHOOK_URL: Optional[str] = None

    HUBSPOT_ACCESS_TOKEN: Optional[str] = None
    HUBSPOT_PORTAL_ID: Optional[str] = None

    CALCOM_BASE_URL: str = "http://localhost:3000"
    CALCOM_API_KEY: Optional[str] = None
    CALCOM_EVENT_TYPE_ID: Optional[str] = None

    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    CFPB_API_BASE: str = (
        "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1"
    )

    LIVE_OUTBOUND: bool = False
    STAFF_SINK_NUMBER: Optional[str] = None

    @field_validator("LIVE_OUTBOUND", mode="before")
    @classmethod
    def _parse_live_outbound(cls, v):
        if v is None or v == "":
            return False
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return bool(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
