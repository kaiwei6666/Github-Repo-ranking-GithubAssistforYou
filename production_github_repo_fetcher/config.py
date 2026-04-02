from __future__ import annotations

import os
from dataclasses import dataclass


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


@dataclass(frozen=True)
class Settings:
    github_api_base_url: str
    github_token: str | None
    db_path: str
    target_repos: int
    min_remaining_requests: int
    request_timeout: float
    max_retries: int
    retry_backoff_seconds: float
    log_level: str
    user_agent: str

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            github_api_base_url=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com"),
            github_token=os.getenv("GITHUB_TOKEN"),
            db_path=os.getenv("GITHUB_FETCHER_DB_PATH", "github_repos.db"),
            target_repos=_get_int("GITHUB_FETCHER_TARGET_REPOS", 1000),
            min_remaining_requests=_get_int("GITHUB_FETCHER_MIN_REMAINING_REQUESTS", 10),
            request_timeout=_get_float("GITHUB_FETCHER_REQUEST_TIMEOUT", 20.0),
            max_retries=_get_int("GITHUB_FETCHER_MAX_RETRIES", 3),
            retry_backoff_seconds=_get_float("GITHUB_FETCHER_RETRY_BACKOFF_SECONDS", 2.0),
            log_level=os.getenv("GITHUB_FETCHER_LOG_LEVEL", "INFO").upper(),
            user_agent=os.getenv("GITHUB_FETCHER_USER_AGENT", "github-random-repo-fetcher-production"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.target_repos <= 0:
            raise ValueError("target_repos must be greater than 0")
        if self.min_remaining_requests < 0:
            raise ValueError("min_remaining_requests cannot be negative")
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be greater than 0")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
