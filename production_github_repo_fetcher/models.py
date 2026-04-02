from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoRecord:
    id: int
    repo_name: str
    full_name: str
    owner: str
    description: str | None
    stars: int
    forks: int
    watchers: int
    language: str
    topics: str
    created_at: str | None
    updated_at: str | None
    pushed_at: str | None
    homepage: str | None
    repo_url: str
    readme: str | None
    license: str | None
    open_issues: int
    size: int
    default_branch: str | None
    score: float
    collected_at: str


@dataclass(frozen=True)
class RateLimitSnapshot:
    resource: str
    remaining: int | None
    reset_at: int | None
