import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pytest_collection_modifyitems(config, items):
    from agent import db
    if not db.db_path().exists():
        skip = pytest.mark.skip(reason="database not built: run `make data`")
        for item in items:
            if "needs_db" in item.keywords:
                item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_db: requires the generated DuckDB file")
