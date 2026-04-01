import time
from datetime import datetime, timezone
from typing import Optional

import github_random_repo_fetcher as fetcher


POLL_SECONDS = 30


def get_next_reset_epoch() -> Optional[int]:
    reset_values = []
    for resource in ("core", "search"):
        value = fetcher.get_state(f"rate_limit_reset_{resource}")
        if value:
            try:
                reset_values.append(int(value))
            except ValueError:
                continue
    return max(reset_values) if reset_values else None


def sleep_until_reset() -> None:
    reset_at = get_next_reset_epoch()
    if not reset_at:
        print(f"No reset time recorded. Sleeping for {POLL_SECONDS} seconds before retrying.")
        time.sleep(POLL_SECONDS)
        return

    now = int(time.time())
    wait_seconds = max(reset_at - now + 5, 5)
    reset_text = datetime.fromtimestamp(reset_at, tz=timezone.utc).isoformat()
    print(f"Waiting {wait_seconds} seconds until rate limit reset at {reset_text}")
    time.sleep(wait_seconds)


def main() -> None:
    fetcher.init_db()

    while True:
        saved_count = fetcher.count_saved_repos()
        if saved_count >= fetcher.TARGET_REPOS:
            print(f"Reached target: {saved_count} repositories saved.")
            return

        print(f"Current progress: {saved_count}/{fetcher.TARGET_REPOS}")
        fetcher.fetch_until_target()

        updated_count = fetcher.count_saved_repos()
        if updated_count >= fetcher.TARGET_REPOS:
            print(f"Reached target: {updated_count} repositories saved.")
            return

        if updated_count == saved_count:
            sleep_until_reset()
        else:
            time.sleep(1)


if __name__ == "__main__":
    main()
