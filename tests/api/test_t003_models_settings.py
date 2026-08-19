"""T003 — shared models + settings load and behave correctly."""
from __future__ import annotations

import pytest

from api.schemas.common import Page, PageParams
from api.settings import Settings, get_settings


def test_settings_load_defaults():
    s = get_settings()
    assert s.database_url.startswith("postgresql://")
    assert s.queue_url.startswith("redis://")
    assert s.max_ingest_batch_size == 1000
    assert s.default_page_size == 50


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("BRIDGEGUARD_DATABASE_URL", "postgresql://db:5432/test")
    monkeypatch.setenv("BRIDGEGUARD_MAX_INGEST_BATCH_SIZE", "42")
    s = Settings()
    assert s.database_url == "postgresql://db:5432/test"
    assert s.max_ingest_batch_size == 42


def test_pageparams_offset():
    assert PageParams(page=1, page_size=50).offset == 0
    assert PageParams(page=3, page_size=20).offset == 40


def test_pageparams_caps_enforced():
    with pytest.raises(ValueError):
        PageParams(page=0, page_size=50)
    with pytest.raises(ValueError):
        PageParams(page=1, page_size=10_000)


def test_page_has_next():
    p = Page[int](items=[1, 2], page=1, page_size=2, total=5)
    assert p.has_next is True
    last = Page[int](items=[5], page=3, page_size=2, total=5)
    assert last.has_next is False
