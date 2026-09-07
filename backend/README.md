# IRYA Backend

## Requirements

- Python 3.12
- uv

## Install

```bash
uv sync
```

## Environment

```bash
cp .env.example .env
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

## Test

```bash
uv run pytest
```

## Lint

```bash
uv run ruff check .
```

## Format

```bash
uv run ruff format .
```
