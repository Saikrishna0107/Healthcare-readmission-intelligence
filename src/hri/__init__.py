"""Hospital Readmission Intelligence."""

from pathlib import Path

__version__ = "0.1.0"

# The package is installed in editable mode from the repository, so the project root is two
# levels above this file (src/hri/__init__.py). Data and config paths are resolved from here,
# which lets the pipeline run from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
