"""Finding and naming input datasets.

Pure standard library, so it can be imported and tested without the geo stack.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

#: Formats GDAL/OGR reads out of the box and that this pipeline accepts.
SUPPORTED_EXTENSIONS = frozenset(
    {".shp", ".geojson", ".json", ".gpkg", ".gml", ".kml", ".fgb", ".tab"}
)

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Turn an arbitrary filename into a layer slug.

    The result matches the CHECK constraint on ``layers.name``: lowercase
    alphanumerics and underscores, never starting with a digit-only prefix that
    the database would reject.

    >>> slugify("NE 10m Admin 0 - Countries.shp")
    'ne_10m_admin_0_countries_shp'
    >>> slugify("2024 census blocks")
    'l_2024_census_blocks'
    """
    slug = _NON_SLUG.sub("_", value.strip().lower()).strip("_")
    if not slug:
        raise ValueError(f"Cannot derive a layer name from {value!r}")
    if not slug[0].isalpha():
        # The column CHECK allows a leading digit, but a leading digit makes an
        # awkward identifier elsewhere, so prefix it.
        slug = f"l_{slug}"
    return slug


def layer_name_for(path: Path) -> str:
    """Derive the default layer slug from a file path."""
    return slugify(path.stem)


def title_for(path: Path) -> str:
    """Human-readable default title: 'ne_10m_rivers' -> 'Ne 10m Rivers'."""
    words = _NON_SLUG.sub(" ", path.stem.lower()).split()
    return " ".join(word.capitalize() for word in words) or path.stem


def discover(paths: Iterable[str | Path], *, recursive: bool = True) -> list[Path]:
    """Expand the CLI's path arguments into a sorted list of readable datasets.

    Files are taken as-is (and validated); directories are walked for any
    supported extension.
    """
    found: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            found.extend(
                candidate
                for candidate in sorted(path.glob(pattern))
                if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif path.is_file():
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise ValueError(
                    f"{path} has unsupported extension {path.suffix!r}; "
                    f"supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                )
            found.append(path)
        else:
            raise FileNotFoundError(f"No such file or directory: {path}")

    # A directory walk can surface the same file twice via overlapping args.
    unique: dict[Path, None] = {}
    for path in found:
        unique.setdefault(path.resolve(), None)
    return list(unique)
