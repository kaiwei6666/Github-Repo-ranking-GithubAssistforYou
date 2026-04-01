import base64
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests


GITHUB_API = "https://api.github.com"
DB_PATH = "github_repos.db"
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
            CREATE TABLE IF NOT EXISTS github_repos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                language TEXT,
                forks INTEGER NOT NULL,
                stars INTEGER NOT NULL,
                watching INTEGER NOT NULL,
                readme TEXT,
                url TEXT,
                fetched_at TEXT NOT NULL
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
        rows = conn.execute("SELECT repo_id FROM github_repos").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def count_saved_repos(db_path: str = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM github_repos").fetchone()
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


def fetch_readme(owner: str, repo: str, db_path: str = DB_PATH) -> str:
    response = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/readme",
        headers=github_headers(),
        timeout=20,
    )
    update_rate_limit_state(response, db_path)

    remaining = response.headers.get("X-RateLimit-Remaining")
    reset_at = response.headers.get("X-RateLimit-Reset")
    resource = response.headers.get("X-RateLimit-Resource", "core")

    if response.status_code == 404:
        return "README not found."

    raise_for_rate_limit(response)

    response.raise_for_status()

    if remaining is not None and int(remaining) <= MIN_REMAINING_REQUESTS:
        raise RateLimitReached(
            int(reset_at) if reset_at else None,
            f"GitHub {resource} rate limit is low ({remaining} remaining).",
        )

    data = response.json()
    content = data.get("content", "")
    encoding = data.get("encoding")

    if encoding == "base64" and content:
        try:
            return base64.b64decode(content).decode("utf-8", errors="ignore")
        except Exception:
            return "README decode failed."
    return "README content is not base64."


def get_random_repo_info(existing_repo_ids: Set[int], db_path: str = DB_PATH) -> Dict[str, Any]:
    repo = pick_random_repo(existing_repo_ids, db_path=db_path)
    owner = repo["owner"]["login"]
    name = repo["name"]
    repo_detail = fetch_repo_detail(owner, name, db_path=db_path)
    readme_text = fetch_readme(owner, name, db_path=db_path)

    return {
        "repo_id": repo_detail["id"],
        "title": repo_detail["full_name"],
        "language": repo_detail.get("language") or "Unknown",
        "forks": repo_detail.get("forks_count", 0),
        "stars": repo_detail.get("stargazers_count", 0),
        "watching": repo_detail.get("subscribers_count", 0),
        "readme": readme_text,
        "url": repo_detail.get("html_url"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def save_to_sqlite(repo_info: Dict[str, Any], db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO github_repos (
                repo_id, title, language, forks, stars, watching, readme, url, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo_info["repo_id"],
                repo_info["title"],
                repo_info["language"],
                repo_info["forks"],
                repo_info["stars"],
                repo_info["watching"],
                repo_info["readme"],
                repo_info["url"],
                repo_info["fetched_at"],
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
            if repo_info["repo_id"] in existing_repo_ids:
                continue

            save_to_sqlite(repo_info, db_path=db_path)
            existing_repo_ids.add(repo_info["repo_id"])
            saved_count += 1
            set_state("last_success_at", datetime.now(timezone.utc).isoformat(), db_path)

            print(
                f"[{saved_count}/{target_repos}] "
                f"Saved {repo_info['title']} | Stars: {repo_info['stars']} | {repo_info['url']}"
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
