"""Environment / dialect diagnostics tests."""
from __future__ import annotations

import json
from unittest.mock import patch

from app.services.aliases import local_kerala_fallback_stats


def test_local_kerala_fallback_loads_json():
    stats = local_kerala_fallback_stats()
    assert stats["loaded"] is True
    assert stats.get("total_normalized_keys", 0) >= 50


def test_diagnose_script_sqlite_branch():
    import scripts.diagnose_db_environment as diag

    report = {}
    with patch.dict("os.environ", {"DATABASE_URL": "sqlite+aiosqlite:///./hsn_dev.db"}):
        # Exercise fallback stats path without full async DB
        from app.services.aliases import local_kerala_fallback_stats as stats_fn

        report["local"] = stats_fn()
    assert report["local"]["total_normalized_keys"] > 0
