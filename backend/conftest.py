"""Root conftest.py for the backend test suite.

Adds backend/src to sys.path so tests can import engineering_drawing_analyzer
without requiring a prior `pip install -e .`.
"""

import sys
from pathlib import Path

# Insert backend/src at the front of sys.path so the package is importable
# whether or not it has been installed.
_src = Path(__file__).parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
