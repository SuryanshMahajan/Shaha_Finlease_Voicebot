from functools import lru_cache
import re
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import NoDecode
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    admin_username: str = ""
    admin_password_hash: str = ""
    jwt_secret: str = ""
    auth_rate_limit_per_minute: int = Field(default=5, ge=1, le=1000)
    verification_rate_limit_per_minute: int = Field(default=10, ge=1, le=1000)
    security_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    outbound_calling_enabled: bool = False
    calling_timezone: str = "Asia/Kolkata"
    calling_hour_start: int = Field(default=8, ge=0, le=23)
    calling_hour_end: int = Field(default=19, ge=1, le=24)
    transcript_retention_days: int = Field(default=180, ge=7, le=3650)
    twilio_account_sid: str = ""
    twilio_auth_token: str = Field(default="", repr=False)
    twilio_public_base_url: str = ""
    llm_provider: str = "none"
    gemini_api_key: str = Field(default="", repr=False)
    gemini_model: str = "gemini-3.5-flash-lite"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def require_postgres(cls, value: str) -> str:
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if not value.startswith(("postgresql+psycopg://", "mssql+pymssql://")):
            raise ValueError("DATABASE_URL must use PostgreSQL with psycopg or SQL Server with pymssql")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("calling_timezone")
    @classmethod
    def validate_calling_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("CALLING_TIMEZONE must be a valid IANA timezone.") from exc
        return value

    @model_validator(mode="after")
    def validate_calling_hours(self):
        if self.calling_hour_start >= self.calling_hour_end:
            raise ValueError("CALLING_HOUR_START must be before CALLING_HOUR_END.")
        return self

    @field_validator("twilio_account_sid")
    @classmethod
    def validate_twilio_account_sid(cls, value: str) -> str:
        if value and not re.fullmatch(r"AC[0-9a-fA-F]{32}", value):
            raise ValueError("TWILIO_ACCOUNT_SID must be an Account SID or blank.")
        return value

    @field_validator("twilio_public_base_url")
    @classmethod
    def validate_twilio_public_base_url(cls, value: str) -> str:
        if not value:
            return value
        from urllib.parse import urlparse

        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("TWILIO_PUBLIC_BASE_URL must be an HTTPS origin without credentials, path, query, or fragment.")
        return value.rstrip("/")

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, value: str) -> str:
        if value not in {"none", "gemini"}:
            raise ValueError("LLM_PROVIDER must be none or gemini.")
        return value

    @field_validator("gemini_model")
    @classmethod
    def validate_gemini_model(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value):
            raise ValueError("GEMINI_MODEL is invalid.")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

