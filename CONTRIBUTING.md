# Contributing to PyNeats

Thank you for your interest in contributing to **PyNeats**! We welcome contributions of all kinds, including bug reports, feature requests, documentation improvements, and code contributions.

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **uv** (fast Python package manager) – [Installation guide](https://docs.astral.sh/uv/getting-started/installation/)
- **make** (build automation tool)

### Setup

1. **Fork and clone** the repository:

   ```bash
   git clone https://github.com/your-username/PyNeats.git
   cd PyNeats
   ```

2. **Install dependencies**:

   ```bash
   make install
   ```

3. **Install pre-commit hooks** (required for contributors):

   ```bash
   make pre-commit-install
   ```

   This enables automatic code formatting and commit message validation.

---

## Development Workflow

### Available Commands

```bash
make help              # Show all available commands
make format            # Format code with ruff
make lint              # Run linting and type checking
make test              # Run tests with coverage
make test-fast         # Run tests without coverage (faster)
make test-unit         # Run unit tests only (no external data)
make check             # Run all checks (lint + audit + test)
make pre-commit        # Run pre-commit on all files
```

### Running Tests

```bash
# Unit tests only (no external data required)
make test-unit

# With BADA data
make test BADA_PATH=/path/to/bada

# With BADA and weather data
make test BADA_PATH=/path/to/bada WEATHER_PATH=/path/to/weather
```

---

## Code Style

We use **Ruff** for formatting/linting and **mypy** for type checking.

```bash
# Format code
make format

# Check for issues
make lint
```

Pre-commit hooks will automatically format code and check for issues before each commit.

---

## Commit Messages

We use **Conventional Commits** format. Pre-commit hooks enforce this.

```
<type>(<scope>): <description>

[optional body]
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`, `build`

**Examples**:
```
feat(parser): add support for OpenSky format
fix(emissions): correct fuel flow calculation
docs(readme): update installation instructions
```

---

## Making Changes

1. **Create a feature branch**:

   ```bash
   git checkout -b feature/my-new-feature
   ```

2. **Make changes** and write tests for new functionality.

3. **Run checks locally**:

   ```bash
   make check
   ```

4. **Commit your changes** (pre-commit hooks will run automatically):

   ```bash
   git add .
   git commit -m "feat(scope): add new feature"
   ```

---

## Pull Request

1. **Push** your branch:

   ```bash
   git push origin feature/my-new-feature
   ```

2. **Open a pull request** against the `main` branch.

3. **Ensure CI passes** – all checks must be green.

4. **Respond to review comments** and make updates as needed.

---

## Additional Notes

- **Documentation**: Update README.md or add docstrings as needed. See the
  [Documentation](#documentation) section below for building and previewing.
- **Dependencies**: Add runtime dependencies to `pyproject.toml` under `dependencies`. For dev tools, add to `[dependency-groups]` dev.
- **Tests**: New features should include tests. Use `@pytest.mark.requires_bada` or `@pytest.mark.requires_weather` for tests requiring external data.

---

## Documentation

The docs live in [`docs/`](docs/) and are published with [MkDocs + Material](https://squidfunk.github.io/mkdocs-material/).

### Build and preview locally

```bash
# Install the docs dependency group
uv sync --group docs

# Live-preview at http://127.0.0.1:8000
uv run mkdocs serve

# Build the static site to ./site (strict mode catches broken refs)
uv run mkdocs build --strict
```

### Structure (Diátaxis)

- `docs/tutorials/` — step-by-step learning paths (for new users)
- `docs/howto/` — task-oriented recipes (for users with a specific goal)
- `docs/reference/` — API, input/output schemas, example scripts
- `docs/explanation/` — methodology, architecture, design choices
- `docs/glossary.md` — project-wide glossary

API reference pages are generated automatically from source docstrings by
[`docs/gen_ref_pages.py`](docs/gen_ref_pages.py) — do not hand-edit
`docs/reference/api/`.

### Docstring conventions

- **Style**: Google (matches `mkdocstrings` configuration in `mkdocs.yml`).
- **Public symbols** must carry a docstring. Tier-A entry points (step
  `run()` methods, runner constructors, public registry functions) must
  document `Args`, `Returns` and `Raises` sections.
- Run `uv run pydocstyle src/pyneats/` to check locally.

### Code examples in docs

Code blocks in `docs/*.md` that use `python` fences are intended to be
runnable. When adding a new code example, verify it matches the real API —
`mkdocs build --strict` catches broken internal references and missing anchor
targets (via the `htmlproofer` plugin), but it cannot catch semantic drift
(e.g. a renamed function). Prefer importing from `pyneats` public exports
rather than from `_private` modules.

---

Thank you for helping improve **PyNeats**!
