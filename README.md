# Weekly Team Pulse Check

A self-hosted Django app that gives a project lead a weekly, anonymous read on how the team is doing. See `_docs/plan.md` for the scope.

## Requirements

- Python 3.14
- [uv](https://docs.astral.sh/uv/)

## Install

```sh
uv sync
```

## Run the dev server

```sh
uv run python manage.py migrate
uv run python manage.py runserver
```

The app runs at http://127.0.0.1:8000/. The health check is at http://127.0.0.1:8000/health/ and returns `ok`.

## Run the tests

```sh
uv run pytest                        # the whole suite
uv run pytest tests/test_health.py   # one test file
```
