"""Configuration parsing. No database required."""

from __future__ import annotations

import pytest

from geoplatform.config import get_settings, normalise_dsn


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgresql://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql://u:p@h/db"),
        ("not-a-url", "not-a-url"),
    ],
)
def test_normalise_dsn_strips_driver_suffix(raw: str, expected: str) -> None:
    assert normalise_dsn(raw) == expected


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@example:5432/db")
    monkeypatch.setenv("TILE_EXTENT", "512")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test ,")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.dsn == "postgresql://u:p@example:5432/db"
        assert settings.tile_extent == 512
        assert settings.cors_origins == ("http://a.test", "http://b.test")
    finally:
        get_settings.cache_clear()


def test_settings_reject_out_of_range_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TILE_BUFFER", "99999")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="TILE_BUFFER must be <= 1024"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_settings_reject_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_FEATURES", "lots")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="MAX_FEATURES must be an integer"):
            get_settings()
    finally:
        get_settings.cache_clear()
