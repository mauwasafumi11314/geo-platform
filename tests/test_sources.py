"""Unit tests for input discovery and naming. No database required."""

from __future__ import annotations

from pathlib import Path

import pytest

from geoplatform.etl.sources import discover, layer_name_for, slugify, title_for


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("rivers", "rivers"),
        ("NE 10m Admin 0 - Countries", "ne_10m_admin_0_countries"),
        ("  spaced  out  ", "spaced_out"),
        ("Tokyo/Wards", "tokyo_wards"),
        ("2024_blocks", "l_2024_blocks"),
        ("UPPER_CASE", "upper_case"),
    ],
)
def test_slugify(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


def test_slugify_rejects_empty() -> None:
    with pytest.raises(ValueError, match="Cannot derive a layer name"):
        slugify("---")


def test_slug_matches_database_constraint() -> None:
    """layers.name is CHECKed against ^[a-z0-9][a-z0-9_]*$."""
    import re

    pattern = re.compile(r"^[a-z0-9][a-z0-9_]*$")
    for raw in ["Rivers 2024", "2024 census", "ne_10m_admin_0_countries"]:
        assert pattern.match(slugify(raw)), raw


def test_layer_name_and_title_from_path() -> None:
    path = Path("/data/ne_10m_admin_0_countries.shp")
    assert layer_name_for(path) == "ne_10m_admin_0_countries"
    assert title_for(path) == "Ne 10m Admin 0 Countries"


def test_discover_walks_directories(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.geojson").write_text("{}")
    (tmp_path / "nested" / "b.shp").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("ignored")

    found = discover([tmp_path])
    assert [p.name for p in found] == ["a.geojson", "b.shp"]


def test_discover_respects_no_recursive(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.geojson").write_text("{}")
    (tmp_path / "nested" / "b.shp").write_bytes(b"")

    found = discover([tmp_path], recursive=False)
    assert [p.name for p in found] == ["a.geojson"]


def test_discover_deduplicates_overlapping_arguments(tmp_path: Path) -> None:
    target = tmp_path / "a.geojson"
    target.write_text("{}")
    assert len(discover([tmp_path, target])) == 1


def test_discover_rejects_unsupported_extension(tmp_path: Path) -> None:
    bad = tmp_path / "data.csv"
    bad.write_text("x")
    with pytest.raises(ValueError, match="unsupported extension"):
        discover([bad])


def test_discover_reports_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover([tmp_path / "nope"])
