"""Auto-generate API reference pages by walking the source tree.

This script is executed by the mkdocs-gen-files plugin during build.
It scans ``src/pyneats/`` for Python modules and generates a
``::: module.path`` page for each, which mkdocstrings then renders.

See: https://mkdocstrings.github.io/recipes/#automatic-code-reference-pages
"""
from pathlib import Path

import mkdocs_gen_files

nav = mkdocs_gen_files.Nav()
src = Path("src")

for path in sorted(src.rglob("*.py")):
    # Skip private / dunder modules (but keep __init__.py)
    if any(part.startswith("_") for part in path.parts if part != "__init__.py"):
        if path.name != "__init__.py":
            continue

    module_path = path.relative_to(src).with_suffix("")
    parts = list(module_path.parts)

    # __init__.py → package index
    if parts[-1] == "__init__":
        parts = parts[:-1]
        if not parts:
            continue

    # doc_path is relative to the virtual "reference/api/" section
    doc_path = Path(*parts).with_suffix(".md")
    full_doc_path = Path("reference", "api", *parts).with_suffix(".md")
    module_name = ".".join(parts)

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        fd.write(f"# `{module_name}`\n\n::: {module_name}\n")

    mkdocs_gen_files.set_edit_path(full_doc_path, Path("../src") / path)
    nav[parts] = doc_path.as_posix()

with mkdocs_gen_files.open("reference/api/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
