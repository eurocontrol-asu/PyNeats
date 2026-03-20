.PHONY: install check lint test test-fast test-unit format audit docs-serve docs-build clean pre-commit pre-commit-install help

# ============================================
# Configuration (can be overridden via CLI or environment)
# ============================================
# Usage:
#   make test BADA_PATH=/path/to/bada WEATHER_PATH=/path/to/weather
#   BADA_PATH=/path/to/bada make test
#
BADA_PATH ?=
WEATHER_PATH ?=

# Build pytest arguments based on provided paths
PYTEST_ARGS :=
ifdef BADA_PATH
    PYTEST_ARGS += --bada-path=$(BADA_PATH)
endif
ifdef WEATHER_PATH
    PYTEST_ARGS += --weather-path=$(WEATHER_PATH)
endif

# ============================================
# Targets
# ============================================

install:  ## Install all dependencies
	uv sync --all-groups
	uv run pip install pybada==0.1.10 --no-deps --ignore-requires-python
	uv pip install -e .   # triggers hatch-vcs, generates src/pyneats/_version.py

check: lint audit test  ## Run all checks

lint:  ## Run linting and type checking
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	uv run mypy src/pyneats/

test:  ## Run tests with coverage (use BADA_PATH= WEATHER_PATH= for data paths)
	uv run pytest tests/ --cov=src --cov-report=term-missing $(PYTEST_ARGS)

test-fast:  ## Run tests without coverage (faster)
	uv run pytest tests/ -v $(PYTEST_ARGS)

test-unit:  ## Run unit tests only (no BADA/weather required)
	uv run pytest tests/ -v -m "not requires_bada and not requires_weather"

format:  ## Format code
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

audit:  ## Security audit (informational, won't fail)
	uv run pip-audit --skip-editable || true

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
	@echo "Usage: make [target] [BADA_PATH=/path/to/bada] [WEATHER_PATH=/path/to/weather]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make test                                    # Run tests (skip BADA/weather tests)"
	@echo "  make test BADA_PATH=/data/bada               # Run tests with BADA data"
	@echo "  make test BADA_PATH=/data/bada WEATHER_PATH=/data/weather"
	@echo "  make test-unit                               # Run only unit tests (no external data)"

.DEFAULT_GOAL := help
