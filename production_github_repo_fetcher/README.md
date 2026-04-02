# Production GitHub Repo Fetcher

This folder contains a production-style refactor of the original script.

## Features

- Structured module layout
- Centralized configuration
- Shared GitHub API client with retry support
- SQLite repository and state storage
- Structured logging
- Graceful rate-limit handling
- Basic unit tests with `unittest`

## Quick Start

```powershell
$env:GITHUB_TOKEN="your_token_here"
python -m production_github_repo_fetcher.main --target-repos 10
```

Optional environment variables:

- `GITHUB_FETCHER_DB_PATH`
- `GITHUB_FETCHER_TARGET_REPOS`
- `GITHUB_FETCHER_MIN_REMAINING_REQUESTS`
- `GITHUB_FETCHER_REQUEST_TIMEOUT`
- `GITHUB_FETCHER_MAX_RETRIES`
- `GITHUB_FETCHER_RETRY_BACKOFF_SECONDS`
- `GITHUB_FETCHER_LOG_LEVEL`

## Run Tests

```powershell
python -m unittest discover -s production_github_repo_fetcher\tests
```
