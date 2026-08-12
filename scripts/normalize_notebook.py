"""Normalize an executed notebook without discarding its useful outputs.

Jupyter writes wall-clock timestamps to code-cell metadata while executing a
notebook. They do not affect the analysis, but they make a deterministic run
look dirty in Git. This module strips only volatile metadata and pins a small,
portable notebook-level metadata envelope.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat

STABLE_NOTEBOOK_METADATA = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}


def normalize_notebook(path: Path) -> None:
    """Strip execution timestamps while preserving code, counts, and outputs."""
    notebook = nbformat.read(path, as_version=4)
    notebook["metadata"] = STABLE_NOTEBOOK_METADATA.copy()
    for cell in notebook.cells:
        cell_metadata = dict(cell.get("metadata", {}))
        cell_metadata.pop("execution", None)
        cell["metadata"] = cell_metadata
    nbformat.write(notebook, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebook", type=Path)
    args = parser.parse_args()
    normalize_notebook(args.notebook)


if __name__ == "__main__":
    main()
