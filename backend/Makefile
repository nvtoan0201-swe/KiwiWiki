# Phase 0 task scripts. Assumes the venv at .venv (or PY override).
PY ?= .venv/bin/python

.PHONY: install migrate downgrade run test lint format typecheck check seed eval smoke

install:
	$(PY) -m pip install -e ".[dev]"

migrate:
	$(PY) -m alembic upgrade head

downgrade:
	$(PY) -m alembic downgrade -1

run:
	$(PY) -m uvicorn app.main:app --reload

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check app tests eval
	$(PY) -m black --check app tests eval

format:
	$(PY) -m ruff check --fix app tests eval
	$(PY) -m black app tests eval

typecheck:
	$(PY) -m mypy app

# Full gate matching the Phase 0 Definition of Done.
check: lint typecheck test

seed:
	$(PY) -m scripts.seed

# Phase 7: eval scorecard artifact (deterministic gates; exits non-zero on regression).
eval:
	$(PY) -m eval.run

# Phase 7: post-deploy smoke test against a running deployment (API_URL=...).
smoke:
	$(PY) -m scripts.smoke_test
