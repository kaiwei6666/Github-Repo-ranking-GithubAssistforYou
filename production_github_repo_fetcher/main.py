from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from production_github_repo_fetcher.config import Settings
    from production_github_repo_fetcher.db import init_db
    from production_github_repo_fetcher.exceptions import RateLimitReached
    from production_github_repo_fetcher.github_client import GitHubClient
    from production_github_repo_fetcher.logging_utils import configure_logging
    from production_github_repo_fetcher.repository import SQLiteRepoStore
    from production_github_repo_fetcher.service import FetcherService
else:
    from .config import Settings
    from .db import init_db
    from .exceptions import RateLimitReached
    from .github_client import GitHubClient
    from .logging_utils import configure_logging
    from .repository import SQLiteRepoStore
    from .service import FetcherService


LOGGER = logging.getLogger(__name__)


def parse_args(settings: Settings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch GitHub repository metadata into SQLite.")
    parser.add_argument("--db-path", default=settings.db_path, help="Path to the SQLite database.")
    parser.add_argument(
        "--target-repos",
        type=int,
        default=settings.target_repos,
        help="How many unique repositories to save.",
    )
    parser.add_argument(
        "--resume-on-rate-limit",
        action="store_true",
        help="Sleep until reset time and continue when a rate limit is reached.",
    )
    return parser.parse_args()


def format_reset_time(reset_at: int | None) -> str:
    if reset_at is None:
        return "unknown"
    return datetime.fromtimestamp(reset_at, tz=timezone.utc).isoformat()


def sleep_until_reset(reset_at: int | None) -> None:
    if reset_at is None:
        time.sleep(30)
        return
    wait_seconds = max(reset_at - int(time.time()) + 5, 5)
    LOGGER.warning(
        "Sleeping until rate limit reset",
        extra={"reset_at": format_reset_time(reset_at), "wait_seconds": wait_seconds},
    )
    time.sleep(wait_seconds)


def main() -> int:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    args = parse_args(settings)

    init_db(args.db_path)
    store = SQLiteRepoStore(args.db_path)
    client = GitHubClient(settings)
    service = FetcherService(client, store)

    try:
        while True:
            service.fetch_until_target(args.target_repos)
            return 0
    except RateLimitReached as exc:
        LOGGER.warning(
            "Rate limit reached",
            extra={
                "resource": exc.resource,
                "reset_at": format_reset_time(exc.reset_at),
                "rate_limit_detail": str(exc),
            },
        )
        if not args.resume_on_rate_limit:
            return 2
        sleep_until_reset(exc.reset_at)
        return main()
    except Exception:
        LOGGER.exception("Fetcher failed")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
