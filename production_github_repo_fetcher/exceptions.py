from __future__ import annotations


class FetcherError(Exception):
    """Base exception for this package."""


class RateLimitReached(FetcherError):
    def __init__(self, reset_at: int | None, resource: str, message: str):
        super().__init__(message)
        self.reset_at = reset_at
        self.resource = resource


class RetryableGitHubError(FetcherError):
    """Signals a transient GitHub or network failure."""
