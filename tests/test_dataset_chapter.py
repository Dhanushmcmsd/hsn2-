from __future__ import annotations

from app.services.dataset import get_hsn_by_chapter


def test_get_hsn_by_chapter_returns_entries():
    rows = get_hsn_by_chapter("01")
    assert isinstance(rows, list)
    if rows:
        first = rows[0]
        assert first.chapter == "01"
        assert first.hsn_code
