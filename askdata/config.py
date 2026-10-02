"""Read settings from environment variables and a local .env file.

Model settings have no defaults. Missing values fail during startup so a
configuration problem is visible before the first question is submitted.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from askdata.exceptions import ConfigError


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float
    max_result_rows: int
    query_timeout_seconds: float
    max_upload_mb: int
    max_attempts: int

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def _number(name: str, default, cast):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got '{raw}'.") from exc


def load_settings() -> Settings:
    # Real environment variables win over .env, which is what we want
    # when the app is deployed and the host injects its own values.
    load_dotenv()
    return Settings(
        llm_base_url=_required("LLM_BASE_URL"),
        llm_api_key=_required("LLM_API_KEY"),
        llm_model=_required("LLM_MODEL"),
        llm_timeout_seconds=_number("LLM_TIMEOUT_SECONDS", 60.0, float),
        max_result_rows=_number("MAX_RESULT_ROWS", 200, int),
        query_timeout_seconds=_number("QUERY_TIMEOUT_SECONDS", 5.0, float),
        max_upload_mb=_number("MAX_UPLOAD_MB", 10, int),
        max_attempts=_number("MAX_ATTEMPTS", 2, int),
    )
