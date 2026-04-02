from __future__ import annotations

import base64
import logging
import time
from typing import Any

import requests

from .config import Settings
from .exceptions import RateLimitReached, RetryableGitHubError


LOGGER = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": settings.user_agent,
            }
        )
        if settings.github_token:
            self.session.headers["Authorization"] = f"Bearer {settings.github_token}"

    def close(self) -> None:
        self.session.close()

    def search_repositories(self, *, query: str, page: int, per_page: int = 100) -> tuple[list[dict[str, Any]], dict[str, str]]:
        payload, state_updates = self._request_json(
            "/search/repositories",
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": per_page,
                "page": page,
            },
        )
        return payload.get("items", []), state_updates

    def fetch_repo_detail(self, owner: str, repo: str) -> tuple[dict[str, Any], dict[str, str]]:
        return self._request_json(f"/repos/{owner}/{repo}")

    def fetch_readme(self, owner: str, repo: str) -> tuple[str | None, str, dict[str, str]]:
        payload, state_updates = self._request_json(
            f"/repos/{owner}/{repo}/readme",
            allow_not_found=True,
        )
        if payload is None:
            return None, "not_found", state_updates

        content = payload.get("content", "")
        encoding = payload.get("encoding")
        if encoding != "base64" or not content:
            return None, "invalid_encoding", state_updates

        try:
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
        except Exception:
            return None, "decode_failed", state_updates
        return decoded, "ok", state_updates

    def _request_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        url = f"{self.settings.github_api_base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.settings.request_timeout,
                )
                state_updates = self._extract_rate_limit_state(response)
                self._raise_for_rate_limit(response)

                if allow_not_found and response.status_code == 404:
                    return None, state_updates

                if response.status_code in {400, 401, 422}:
                    response.raise_for_status()

                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RetryableGitHubError(
                        f"Transient GitHub error {response.status_code} for {path}"
                    )

                response.raise_for_status()
                self._raise_if_remaining_is_low(response)
                return response.json(), state_updates
            except RateLimitReached:
                raise
            except (requests.RequestException, RetryableGitHubError) as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                sleep_seconds = self.settings.retry_backoff_seconds * (attempt + 1)
                LOGGER.warning(
                    "Retrying GitHub request",
                    extra={
                        "path": path,
                        "attempt": attempt + 1,
                        "sleep_seconds": sleep_seconds,
                        "error": str(exc),
                    },
                )
                time.sleep(sleep_seconds)

        raise RetryableGitHubError(f"GitHub request failed after retries: {last_error}")

    def _extract_rate_limit_state(self, response: requests.Response) -> dict[str, str]:
        resource = response.headers.get("X-RateLimit-Resource", "core")
        updates: dict[str, str] = {}
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_at = response.headers.get("X-RateLimit-Reset")

        if remaining is not None:
            updates[f"rate_limit_remaining_{resource}"] = remaining
        if reset_at is not None:
            updates[f"rate_limit_reset_{resource}"] = reset_at
        return updates

    def _raise_for_rate_limit(self, response: requests.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_at = response.headers.get("X-RateLimit-Reset")
        resource = response.headers.get("X-RateLimit-Resource", "core")
        message = self._extract_message(response)
        lowered_message = message.lower()

        is_rate_limit = (
            response.status_code == 403
            and (
                remaining == "0"
                or "rate limit" in lowered_message
                or "secondary rate limit" in lowered_message
            )
        )
        if is_rate_limit:
            raise RateLimitReached(
                reset_at=int(reset_at) if reset_at else None,
                resource=resource,
                message=f"GitHub {resource} rate limit reached: {message}",
            )

    def _raise_if_remaining_is_low(self, response: requests.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_at = response.headers.get("X-RateLimit-Reset")
        resource = response.headers.get("X-RateLimit-Resource", "core")
        if remaining is None:
            return
        if int(remaining) <= self.settings.min_remaining_requests:
            raise RateLimitReached(
                reset_at=int(reset_at) if reset_at else None,
                resource=resource,
                message=f"GitHub {resource} rate limit is low ({remaining} remaining).",
            )

    @staticmethod
    def _extract_message(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text
        return str(payload.get("message", ""))
