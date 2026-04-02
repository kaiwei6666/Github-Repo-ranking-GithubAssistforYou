from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any

from .exceptions import RateLimitReached
from .github_client import GitHubClient
from .models import RepoRecord
from .repository import SQLiteRepoStore


LOGGER = logging.getLogger(__name__)

STAR_RANGES = (
    "stars:1..50",
    "stars:51..200",
    "stars:201..1000",
    "stars:1001..5000",
    "stars:5001..20000",
    "stars:>20000",
)


def calculate_repo_score(detail: dict[str, Any]) -> float:
    stars = max(int(detail.get("stargazers_count", 0)), 0)
    forks = max(int(detail.get("forks_count", 0)), 0)
    watchers = max(int(detail.get("subscribers_count", 0)), 0)
    open_issues = max(int(detail.get("open_issues_count", 0)), 0)

    raw_score = (stars * 1.0) + (forks * 0.6) + (watchers * 0.8) - (open_issues * 0.05)
    normalized = raw_score / (raw_score + 5000) if raw_score > 0 else 0.0
    return round(min(max(normalized, 0.0), 1.0), 4)


class FetcherService:
    def __init__(self, client: GitHubClient, store: SQLiteRepoStore):
        self.client = client
        self.store = store

    def fetch_until_target(self, target_repos: int) -> None:
        existing_repo_ids = self.store.load_existing_repo_ids()
        saved_count = len(existing_repo_ids)

        if saved_count >= target_repos:
            LOGGER.info("Target already reached", extra={"saved_count": saved_count})
            return

        while saved_count < target_repos:
            try:
                record, state_updates = self.fetch_one(existing_repo_ids)
                self.store.save_repo_and_states(
                    record,
                    {
                        **state_updates,
                        "last_success_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                existing_repo_ids.add(record.repo_id)
                saved_count += 1
                LOGGER.info(
                    "Repository saved",
                    extra={
                        "saved_count": saved_count,
                        "target_repos": target_repos,
                        "repo_id": record.id,
                        "full_name": record.full_name,
                        "stars": record.stars,
                        "url": record.repo_url,
                    },
                )
            except RateLimitReached:
                raise

        LOGGER.info("Fetch completed", extra={"saved_count": saved_count})

    def fetch_one(self, existing_repo_ids: set[int]) -> tuple[RepoRecord, dict[str, str]]:
        candidate, search_state = self._pick_candidate(existing_repo_ids)
        owner = candidate["owner"]["login"]
        name = candidate["name"]

        detail, detail_state = self.client.fetch_repo_detail(owner, name)
        readme, readme_status, readme_state = self.client.fetch_readme(owner, name)
        collected_at = datetime.now(timezone.utc).isoformat()

        record = RepoRecord(
            id=int(detail["id"]),
            repo_name=name,
            full_name=detail["full_name"],
            owner=owner,
            description=detail.get("description"),
            stars=int(detail.get("stargazers_count", 0)),
            forks=int(detail.get("forks_count", 0)),
            watchers=int(detail.get("subscribers_count", 0)),
            language=detail.get("language") or "Unknown",
            topics=",".join(detail.get("topics", [])),
            created_at=detail.get("created_at"),
            updated_at=detail.get("updated_at"),
            pushed_at=detail.get("pushed_at"),
            homepage=detail.get("homepage"),
            repo_url=detail["html_url"],
            readme=readme,
            license=(detail.get("license") or {}).get("spdx_id"),
            open_issues=int(detail.get("open_issues_count", 0)),
            size=int(detail.get("size", 0)),
            default_branch=detail.get("default_branch"),
            score=calculate_repo_score(detail),
            collected_at=collected_at,
        )
        return record, {**search_state, **detail_state, **readme_state, "last_readme_status": readme_status}

    def _pick_candidate(self, existing_repo_ids: set[int]) -> tuple[dict[str, Any], dict[str, str]]:
        last_error: Exception | None = None
        for _ in range(25):
            star_range = random.choice(STAR_RANGES)
            page = random.randint(1, 10)
            items, state_updates = self.client.search_repositories(
                query=f"{star_range} archived:false mirror:false is:public",
                page=page,
            )
            unseen_items = [item for item in items if int(item["id"]) not in existing_repo_ids]
            if unseen_items:
                return random.choice(unseen_items), state_updates
            last_error = RuntimeError(
                f"No unseen repositories found for query={star_range} page={page}"
            )

        raise RuntimeError(f"Could not find a new repository candidate: {last_error}")
