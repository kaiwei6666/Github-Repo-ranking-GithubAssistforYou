from __future__ import annotations

import unittest
from unittest.mock import patch

from production_github_repo_fetcher.service import FetcherService


class FakeClient:
    def search_repositories(self, *, query: str, page: int, per_page: int = 100):
        return (
            [
                {"id": 100, "owner": {"login": "octocat"}, "name": "hello-world"},
                {"id": 101, "owner": {"login": "someone"}, "name": "repo"},
            ],
            {"rate_limit_remaining_search": "10"},
        )

    def fetch_repo_detail(self, owner: str, repo: str):
        return (
            {
                "id": 101,
                "full_name": f"{owner}/{repo}",
                "language": "Python",
                "forks_count": 5,
                "stargazers_count": 10,
                "subscribers_count": 1,
                "description": "demo",
                "default_branch": "main",
                "homepage": "https://example.com",
                "license": {"spdx_id": "MIT"},
                "topics": ["python"],
                "html_url": f"https://github.com/{owner}/{repo}",
                "open_issues_count": 7,
                "size": 1234,
                "created_at": None,
                "updated_at": None,
                "pushed_at": None,
            },
            {"rate_limit_remaining_core": "20"},
        )

    def fetch_readme(self, owner: str, repo: str):
        return "readme", "ok", {"rate_limit_reset_core": "123456"}


class FakeStore:
    pass


class FetcherServiceTests(unittest.TestCase):
    @patch("production_github_repo_fetcher.service.random.choice", side_effect=["stars:51..200", {"id": 101, "owner": {"login": "someone"}, "name": "repo"}])
    @patch("production_github_repo_fetcher.service.random.randint", return_value=1)
    def test_fetch_one_returns_repo_record(self, _: object, __: object) -> None:
        service = FetcherService(FakeClient(), FakeStore())
        record, state_updates = service.fetch_one(existing_repo_ids={100})

        self.assertEqual(record.id, 101)
        self.assertEqual(record.repo_name, "repo")
        self.assertEqual(record.full_name, "someone/repo")
        self.assertEqual(record.repo_url, "https://github.com/someone/repo")
        self.assertGreaterEqual(record.score, 0.0)
        self.assertIn("rate_limit_remaining_search", state_updates)
        self.assertIn("rate_limit_remaining_core", state_updates)


if __name__ == "__main__":
    unittest.main()
