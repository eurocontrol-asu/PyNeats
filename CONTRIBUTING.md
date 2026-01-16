# Contributing to PyNeats

Thank you for your interest in contributing to **PyNeats**! We welcome contributions of all kinds, including bug reports, feature requests, documentation improvements, and code contributions.

This guide will help you set up your development environment and contribute effectively.

---

## Getting Started

1. **Fork the repository** and clone your fork locally:

   git clone [https://github.com/your-username/pyneats.git](https://github.com/your-username/pyneats.git)
   cd pyneats

2. **Create a virtual environment** (recommended):

   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate     # Windows

3. **Install the package in editable mode with dev dependencies**:

   pip install --upgrade pip
   pip install -e ".[dev]"

---

## Code Style and Quality

We use **Ruff** and **Mypy** to maintain code quality and type safety.

* **Linting**:
  ruff check src tests

* **Type checking**:
  mypy src

* **Auto-fix formatting issues**:
  ruff check --fix src tests

---

## Running Tests

PyNeats uses **pytest**. To run all tests:

```
pytest .
```

Don't forget to define the weather cache path if you want to run also tests involving weather data:

```
pytest . --met-cache-dir=/datasave/NEATS_CLEAN/NyYXp7uG/met_cache
```

For instance.

---

## Making Changes

1. Create a **feature branch**:

   git checkout -b feature/my-new-feature

2. Make your changes and **write tests** for new functionality.

3. Run linting, type checking, and tests locally to ensure nothing is broken:

   ruff check src tests
   mypy src
   pytest .

4. Commit your changes:

   git add .
   git commit -m "Add <short description of change>"

---

## Pull Request

1. Push your branch to your fork:

   git push origin feature/my-new-feature

2. Open a pull request (PR) against the `main` branch of the original repository.

3. Fill in the PR template with a clear description of your changes.

4. Respond to review comments and make updates as needed.

---

## Additional Notes

* **Documentation**: Update `README.md` or add docstrings as needed.
* **Dependencies**: Add new runtime dependencies to `pyproject.toml` under `dependencies`. For dev tools, add under `[project.optional-dependencies]` dev.

---

Thank you for helping improve **PyNeats**! Your contributions make a real difference.

---

This is **fully Markdown**, commands are indented, and you can **copy-paste it directly** into your `CONTRIBUTING.md`.

If you want, I can also make a **super short one-page “Quick Start” version** in Markdown for new contributors. Do you want me to do that?
