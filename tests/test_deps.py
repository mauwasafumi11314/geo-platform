"""Query-parameter parsing. No database required."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from geoplatform.api.deps import NO_BBOX, parse_bbox


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_bbox_means_no_filter(raw: str | None) -> None:
    assert parse_bbox(raw) == NO_BBOX


def test_bbox_is_parsed_in_geojson_order() -> None:
    assert parse_bbox("139.0, 35.0, 140.5, 36.5") == (139.0, 35.0, 140.5, 36.5)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("1,2,3", "four comma-separated values"),
        ("1,2,3,4,5", "four comma-separated values"),
        ("a,b,c,d", "must be numbers"),
        ("10,0,0,10", "ordered west,south,east,north"),
        ("0,10,10,0", "ordered west,south,east,north"),
    ],
)
def test_bad_bbox_is_rejected(raw: str, message: str) -> None:
    with pytest.raises(HTTPException) as excinfo:
        parse_bbox(raw)
    assert excinfo.value.status_code == 422
    assert message in excinfo.value.detail
