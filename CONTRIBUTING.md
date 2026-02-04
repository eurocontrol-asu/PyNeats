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

- **Documentation**: Update README.md or add docstrings as needed.
- **Dependencies**: Add runtime dependencies to `pyproject.toml` under `dependencies`. For dev tools, add to `[dependency-groups]` dev.
- **Tests**: New features should include tests. Use `@pytest.mark.requires_bada` or `@pytest.mark.requires_weather` for tests requiring external data.

---

Thank you for helping improve **PyNeats**!
