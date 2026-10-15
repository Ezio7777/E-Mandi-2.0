.PHONY: install dev worker lint format typecheck test test-int migrate revision seed reseed up down logs

install:
	pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload --port 8000

worker:
	arq app.workers.settings.WorkerSettings

lint:
	ruff check . && mypy app

format:
	ruff check --fix . && ruff format .

typecheck:
	mypy app

test:
	pytest -m "not integration"

test-int:
	pytest -m integration

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

seed:
	python -m scripts.seed

reseed:
	python -m scripts.reset_seed

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100
