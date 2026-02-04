.PHONY: install check lint test test-fast format audit docs-serve docs-build clean pre-commit pre-commit-install help

install:  ## Install all dependencies
	uv sync --all-groups
	uv run pip install pybada --no-deps --ignore-requires-python
	uv run pip install git+https://github.com/dlr-pa/oac.git

check: lint audit test  ## Run all checks

lint:  ## Run linting and type checking
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	uv run mypy src/pyneats/

test:  ## Run tests with coverage
	uv run pytest tests/ --cov=src --cov-report=term-missing

test-fast:  ## Run tests without coverage (faster)
	uv run pytest tests/ -v

format:  ## Format code
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

audit:  ## Security audit
	uv run pip-audit

docs-serve:  ## Serve docs locally
	uv sync --group docs --quiet
	uv run mkdocs serve

docs-build:  ## Build documentation
	uv sync --group docs --quiet
	uv run mkdocs build

clean:  ## Clean build artifacts
	rm -rf build/ dist/ .pytest_cache/ .mypy_cache/ .ruff_cache/ htmlcov/ .coverage coverage.xml site/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	find . -type f -name '*.pyo' -delete 2>/dev/null || true

pre-commit:  ## Run pre-commit on all files
	uv run pre-commit run --all-files

pre-commit-install:  ## Install pre-commit hooks
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg

help:  ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
