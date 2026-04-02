from __future__ import annotations

import unittest
from unittest.mock import Mock

from production_github_repo_fetcher.config import Settings
from production_github_repo_fetcher.exceptions import RateLimitReached
from production_github_repo_fetcher.github_client import GitHubClient


class GitHubClientTests(unittest.TestCase):
    def test_raise_for_rate_limit(self) -> None:
        settings = Settings.from_env()
        client = GitHubClient(settings)
        response = Mock()
        response.status_code = 403
        response.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "123456",
            "X-RateLimit-Resource": "core",
        }
        response.json.return_value = {"message": "API rate limit exceeded"}

        with self.assertRaises(RateLimitReached):
            client._raise_for_rate_limit(response)

        client.close()


if __name__ == "__main__":
    unittest.main()
