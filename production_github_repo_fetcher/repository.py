from __future__ import annotations

import sqlite3
from typing import Iterable

from .db import get_connection
from .models import RateLimitSnapshot, RepoRecord


class SQLiteRepoStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def load_existing_repo_ids(self) -> set[int]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute("SELECT id FROM github_repos").fetchall()
        return {int(row["id"]) for row in rows}

    def count_saved_repos(self) -> int:
        with get_connection(self.db_path) as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM github_repos").fetchone()
        return int(row["total"]) if row else 0

    def get_state(self, key: str) -> str | None:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT state_value FROM fetch_state WHERE state_key = ?",
                (key,),
            ).fetchone()
        return str(row["state_value"]) if row else None

    def get_rate_limit_snapshots(self) -> list[RateLimitSnapshot]:
        snapshots: list[RateLimitSnapshot] = []
        for resource in ("core", "search"):
            remaining = self.get_state(f"rate_limit_remaining_{resource}")
            reset_at = self.get_state(f"rate_limit_reset_{resource}")
            snapshots.append(
                RateLimitSnapshot(
                    resource=resource,
                    remaining=int(remaining) if remaining is not None else None,
                    reset_at=int(reset_at) if reset_at is not None else None,
                )
            )
        return snapshots

    def save_repo_and_states(self, repo: RepoRecord, state_updates: dict[str, str]) -> None:
        with get_connection(self.db_path) as connection:
            self._save_repo(connection, repo)
            self._set_states(connection, state_updates)

    def update_states(self, state_updates: dict[str, str]) -> None:
        with get_connection(self.db_path) as connection:
            self._set_states(connection, state_updates)

    def _save_repo(self, connection: sqlite3.Connection, repo: RepoRecord) -> None:
        connection.execute(
            """
            INSERT INTO github_repos (
                id, repo_name, full_name, owner, description, stars, forks, watchers,
                language, topics, created_at, updated_at, pushed_at, homepage, repo_url,
                readme, license, open_issues, size, default_branch, score, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                repo_name = excluded.repo_name,
                full_name = excluded.full_name,
                owner = excluded.owner,
                description = excluded.description,
                stars = excluded.stars,
                forks = excluded.forks,
                watchers = excluded.watchers,
                language = excluded.language,
                topics = excluded.topics,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                pushed_at = excluded.pushed_at,
                homepage = excluded.homepage,
                repo_url = excluded.repo_url,
                readme = excluded.readme,
                license = excluded.license,
                open_issues = excluded.open_issues,
                size = excluded.size,
                default_branch = excluded.default_branch,
                score = excluded.score,
                collected_at = excluded.collected_at
            """,
            (
                repo.id,
                repo.repo_name,
                repo.full_name,
                repo.owner,
                repo.description,
                repo.stars,
                repo.forks,
                repo.watchers,
                repo.language,
                repo.topics,
                repo.created_at,
                repo.updated_at,
                repo.pushed_at,
                repo.homepage,
                repo.repo_url,
                repo.readme,
                repo.license,
                repo.open_issues,
                repo.size,
                repo.default_branch,
                repo.score,
                repo.collected_at,
            ),
        )

    def _set_states(self, connection: sqlite3.Connection, state_updates: dict[str, str]) -> None:
        if not state_updates:
            return
        connection.executemany(
            """
            INSERT INTO fetch_state (state_key, state_value)
            VALUES (?, ?)
            ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
            """,
            state_updates.items(),
        )
