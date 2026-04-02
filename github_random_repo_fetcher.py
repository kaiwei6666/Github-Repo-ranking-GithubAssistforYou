import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests


GITHUB_API = "https://api.github.com"
DB_PATH = "tools.db"
TARGET_REPOS = 1000
MIN_REMAINING_REQUESTS = 10
MAX_SEARCH_ATTEMPTS = 20


class RateLimitReached(Exception):
    def __init__(self, reset_at: Optional[int], message: str):
        super().__init__(message)
        self.reset_at = reset_at


def github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-random-repo-fetcher",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def init_db(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                github_id INTEGER NOT NULL UNIQUE,
                name TEXT,
                full_name TEXT,
                owner TEXT,
                description TEXT,
                html_url TEXT,
                homepage TEXT,
                stars INTEGER,
                forks INTEGER,
                watchers INTEGER,
                open_issues INTEGER,
                language TEXT,
                license TEXT,
                archived INTEGER,
                disabled INTEGER,
                visibility TEXT,
                created_at TEXT,
                updated_at TEXT,
                pushed_at TEXT,
                default_branch TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fetch_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def set_state(key: str, value: str, db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO fetch_state (state_key, state_value)
            VALUES (?, ?)
            ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
            """,
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_state(key: str, db_path: str = DB_PATH) -> Optional[str]:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT state_value FROM fetch_state WHERE state_key = ?",
            (key,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def load_existing_repo_ids(db_path: str = DB_PATH) -> Set[int]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT github_id FROM tools").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def count_saved_repos(db_path: str = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM tools").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def format_reset_time(reset_at: Optional[int]) -> str:
    if not reset_at:
        return "unknown"
    return datetime.fromtimestamp(reset_at, tz=timezone.utc).isoformat()


def update_rate_limit_state(response: requests.Response, db_path: str = DB_PATH) -> None:
    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_at = response.headers.get("X-RateLimit-Reset")
    resource = response.headers.get("X-RateLimit-Resource", "core")

    if remaining is not None:
        set_state(f"rate_limit_remaining_{resource}", remaining, db_path)
    if reset_at is not None:
        set_state(f"rate_limit_reset_{resource}", reset_at, db_path)


def raise_for_rate_limit(response: requests.Response) -> None:
    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_at = response.headers.get("X-RateLimit-Reset")
    resource = response.headers.get("X-RateLimit-Resource", "core")

    message = ""
    try:
        message = response.json().get("message", "")
    except Exception:
        message = response.text

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
            int(reset_at) if reset_at else None,
            f"GitHub {resource} rate limit reached: {message}",
        )


def safe_get(
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    db_path: str = DB_PATH,
) -> requests.Response:
    response = requests.get(
        f"{GITHUB_API}{path}",
        headers=github_headers(),
        params=params,
        timeout=20,
    )

    update_rate_limit_state(response, db_path)

    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_at = response.headers.get("X-RateLimit-Reset")
    resource = response.headers.get("X-RateLimit-Resource", "core")

    raise_for_rate_limit(response)

    response.raise_for_status()

    if remaining is not None and int(remaining) <= MIN_REMAINING_REQUESTS:
        raise RateLimitReached(
            int(reset_at) if reset_at else None,
            f"GitHub {resource} rate limit is low ({remaining} remaining).",
        )

    return response


def pick_random_repo(existing_repo_ids: Set[int], db_path: str = DB_PATH) -> Dict[str, Any]:
    for page in range(1, 11):
        response = safe_get(
            "/search/repositories",
            params={
                "q": "stars:>0 archived:false",
                "sort": "stars",
                "order": "desc",
                "per_page": 100,
                "page": page,
            },
            db_path=db_path,
        )
        items: List[Dict[str, Any]] = response.json().get("items", [])
        unseen_items = [item for item in items if item["id"] not in existing_repo_ids]
        if unseen_items:
            return unseen_items[0]

    raise RuntimeError("Could not find a new repository in the top 1000 starred repositories.")


def fetch_repo_detail(owner: str, repo: str, db_path: str = DB_PATH) -> Dict[str, Any]:
    response = safe_get(f"/repos/{owner}/{repo}", db_path=db_path)
    return response.json()


def get_random_repo_info(existing_repo_ids: Set[int], db_path: str = DB_PATH) -> Dict[str, Any]:
    repo = pick_random_repo(existing_repo_ids, db_path=db_path)
    owner = repo["owner"]["login"]
    name = repo["name"]
    repo_detail = fetch_repo_detail(owner, name, db_path=db_path)
    license_info = repo_detail.get("license") or {}

    return {
        "github_id": repo_detail["id"],
        "name": repo_detail.get("name"),
        "full_name": repo_detail.get("full_name"),
        "owner": owner,
        "description": repo_detail.get("description"),
        "html_url": repo_detail.get("html_url"),
        "homepage": repo_detail.get("homepage"),
        "stars": repo_detail.get("stargazers_count", 0),
        "forks": repo_detail.get("forks_count", 0),
        "watchers": repo_detail.get("watchers_count", 0),
        "open_issues": repo_detail.get("open_issues_count", 0),
        "language": repo_detail.get("language") or "Unknown",
        "license": license_info.get("name"),
        "archived": int(bool(repo_detail.get("archived", False))),
        "disabled": int(bool(repo_detail.get("disabled", False))),
        "visibility": repo_detail.get("visibility"),
        "created_at": repo_detail.get("created_at"),
        "updated_at": repo_detail.get("updated_at"),
        "pushed_at": repo_detail.get("pushed_at"),
        "default_branch": repo_detail.get("default_branch"),
    }


def save_to_sqlite(repo_info: Dict[str, Any], db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO tools (
                github_id, name, full_name, owner, description, html_url, homepage,
                stars, forks, watchers, open_issues, language, license, archived,
                disabled, visibility, created_at, updated_at, pushed_at, default_branch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo_info["github_id"],
                repo_info["name"],
                repo_info["full_name"],
                repo_info["owner"],
                repo_info["description"],
                repo_info["html_url"],
                repo_info["homepage"],
                repo_info["stars"],
                repo_info["forks"],
                repo_info["watchers"],
                repo_info["open_issues"],
                repo_info["language"],
                repo_info["license"],
                repo_info["archived"],
                repo_info["disabled"],
                repo_info["visibility"],
                repo_info["created_at"],
                repo_info["updated_at"],
                repo_info["pushed_at"],
                repo_info["default_branch"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def print_rate_limit_snapshot(db_path: str = DB_PATH) -> None:
    for resource in ("core", "search"):
        remaining = get_state(f"rate_limit_remaining_{resource}", db_path)
        reset_at = get_state(f"rate_limit_reset_{resource}", db_path)
        if remaining is None and reset_at is None:
            continue
        reset_text = format_reset_time(int(reset_at)) if reset_at else "unknown"
        print(f"{resource} remaining: {remaining}, reset at: {reset_text}")


def fetch_until_target(target_repos: int = TARGET_REPOS, db_path: str = DB_PATH) -> None:
    existing_repo_ids = load_existing_repo_ids(db_path)
    saved_count = len(existing_repo_ids)

    if saved_count >= target_repos:
        print(f"Already saved {saved_count} unique repositories. Nothing to do.")
        return

    while saved_count < target_repos:
        try:
            repo_info = get_random_repo_info(existing_repo_ids, db_path=db_path)
            if repo_info["github_id"] in existing_repo_ids:
                continue

            save_to_sqlite(repo_info, db_path=db_path)
            existing_repo_ids.add(repo_info["github_id"])
            saved_count += 1
            set_state("last_success_at", datetime.now(timezone.utc).isoformat(), db_path)

            print(
                f"[{saved_count}/{target_repos}] "
                f"Saved {repo_info['full_name']} | Stars: {repo_info['stars']} | {repo_info['html_url']}"
            )
        except RateLimitReached as exc:
            reset_text = format_reset_time(exc.reset_at)
            print(str(exc))
            print(f"Progress is saved. Resume after GitHub resets the limit at: {reset_text}")
            print_rate_limit_snapshot(db_path)
            return
        except requests.HTTPError as exc:
            print(f"HTTP error, skipping this repository candidate: {exc}")
            time.sleep(1)
        except Exception as exc:
            print(f"Unexpected error, skipping this repository candidate: {exc}")
            time.sleep(1)

    print(f"Finished. Saved {saved_count} unique repositories.")
    print_rate_limit_snapshot(db_path)


if __name__ == "__main__":
    try:
        init_db()
        fetch_until_target()
    except Exception as exc:
        print(f"Program failed: {exc}")
