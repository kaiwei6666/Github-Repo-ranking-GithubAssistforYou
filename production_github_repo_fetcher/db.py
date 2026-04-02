from __future__ import annotations

import sqlite3


def get_connection(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db(db_path: str) -> None:
    with get_connection(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS github_repos (
                id INTEGER PRIMARY KEY,
                repo_name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                owner TEXT NOT NULL,
                description TEXT,
                stars INTEGER NOT NULL,
                forks INTEGER NOT NULL,
                watchers INTEGER NOT NULL,
                language TEXT,
                topics TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT,
                pushed_at TEXT,
                homepage TEXT,
                repo_url TEXT NOT NULL,
                readme TEXT,
                license TEXT,
                open_issues INTEGER NOT NULL,
                size INTEGER NOT NULL,
                default_branch TEXT,
                score REAL NOT NULL,
                collected_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS fetch_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_github_repos_stars
            ON github_repos (stars DESC)
            """
        )
