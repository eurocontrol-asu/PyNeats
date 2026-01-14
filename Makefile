.PHONY: help install lint format test check audit docs-serve clean

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install all dependencies with uv
	uv sync --all-groups
	uv run pip install pybada --no-deps --ignore-requires-python

format: ## Auto-format code with ruff
	uv run ruff format src/pyneats tests/

lint: ## Run linting (ruff) and type checking (mypy)
	uv run ruff check src/pyneats tests/
	uv run mypy src/pyneats

test: ## Run tests with coverage
	uv run pytest tests/ -v --cov=pyneats --cov-report=term --cov-report=html

audit: ## Run security audit with pip-audit
	uv run pip-audit

check: lint test ## Run all quality checks (lint + test)

docs-serve: ## Serve documentation locally (requires mkdocs)
	uv run mkdocs serve

clean: ## Clean up build artifacts and caches
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
