from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from production_github_repo_fetcher.db import init_db
from production_github_repo_fetcher.models import RepoRecord
from production_github_repo_fetcher.repository import SQLiteRepoStore


class SQLiteRepoStoreTests(unittest.TestCase):
    def test_save_repo_and_state(self) -> None:
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.db"
            init_db(str(db_path))
            store = SQLiteRepoStore(str(db_path))

            store.save_repo_and_states(
                RepoRecord(
                    id=1,
                    repo_name="hello-world",
                    full_name="octocat/hello-world",
                    owner="octocat",
                    description="demo",
                    stars=2,
                    forks=1,
                    watchers=3,
                    language="Python",
                    topics="python,test",
                    created_at=None,
                    updated_at=None,
                    pushed_at=None,
                    homepage="https://example.com",
                    repo_url="https://github.com/octocat/hello-world",
                    readme="hello",
                    license="MIT",
                    open_issues=4,
                    size=100,
                    default_branch="main",
                    score=0.5,
                    collected_at="2026-04-02T00:00:00+00:00",
                ),
                {"last_success_at": "2026-04-02T00:00:00+00:00"},
            )

            self.assertEqual(store.count_saved_repos(), 1)
            self.assertEqual(store.get_state("last_success_at"), "2026-04-02T00:00:00+00:00")
            self.assertEqual(store.load_existing_repo_ids(), {1})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
