"""Command-line interface for the loader.

    geoplatform-etl load ./data --recursive
    geoplatform-etl load ./data/rivers.shp --layer rivers --title "Rivers"
    geoplatform-etl list
    geoplatform-etl drop rivers --yes

The database is always addressed through DATABASE_URL (or --database-url).
Credentials are never read from the source, and never written to it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from geoplatform import __version__
from geoplatform.config import get_settings, normalise_dsn
from geoplatform.etl.sources import SUPPORTED_EXTENSIONS, discover

logger = logging.getLogger("geoplatform.etl")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geoplatform-etl",
        description="Load spatial data into the GeoPlatform PostGIS database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres connection string. Defaults to $DATABASE_URL.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")

    sub = parser.add_subparsers(dest="command", required=True)

    load = sub.add_parser("load", help="Load one or more files or directories.")
    load.add_argument("paths", nargs="+", help="Files or directories to load.")
    load.add_argument(
        "--layer",
        default=None,
        help="Layer slug. Only valid with a single input file; otherwise derived from filenames.",
    )
    load.add_argument("--title", default=None, help="Human-readable layer title.")
    load.add_argument("--description", default=None, help="Layer description.")
    load.add_argument(
        "--append",
        action="store_true",
        help="Add to the existing layer instead of replacing its features.",
    )
    load.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Do not descend into subdirectories.",
    )
    load.add_argument("--min-zoom", type=int, default=0, help="Lowest tile zoom (default 0).")
    load.add_argument("--max-zoom", type=int, default=14, help="Highest tile zoom (default 14).")
    load.add_argument(
        "--assume-srid",
        type=int,
        default=4326,
        help="SRID to assume when a file carries no CRS (default 4326).",
    )
    load.add_argument(
        "--fix-geometry",
        action="store_true",
        help="Run ST_MakeValid's client-side equivalent on invalid geometries.",
    )
    load.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be loaded and exit without touching the database.",
    )

    sub.add_parser("list", help="Show the layers currently in the database.")

    drop = sub.add_parser("drop", help="Delete a layer and all of its features.")
    drop.add_argument("layer", help="Layer slug to delete.")
    drop.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    return parser


def resolve_dsn(explicit: str | None) -> str:
    return normalise_dsn(explicit) if explicit else get_settings().dsn


def _connect(dsn: str):
    # Imported lazily so `--help` and `--version` work without the geo stack.
    import psycopg

    return psycopg.connect(dsn)


def cmd_load(args: argparse.Namespace) -> int:
    from geoplatform.etl.loader import load_dataset

    try:
        paths = discover(args.paths, recursive=args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 2

    if not paths:
        logger.error("No supported spatial files found in %s", ", ".join(args.paths))
        return 2

    if args.layer and len(paths) > 1:
        logger.error("--layer needs exactly one input file, but %d were found", len(paths))
        return 2

    if args.min_zoom > args.max_zoom:
        logger.error("--min-zoom (%d) cannot exceed --max-zoom (%d)", args.min_zoom, args.max_zoom)
        return 2

    if args.dry_run:
        print(f"Would load {len(paths)} file(s):")
        for path in paths:
            print(f"  {path}")
        return 0

    dsn = resolve_dsn(args.database_url)
    failures = 0

    with _connect(dsn) as conn:
        for path in paths:
            try:
                result = load_dataset(
                    conn,
                    Path(path),
                    layer_name=args.layer,
                    title=args.title,
                    description=args.description,
                    replace=not args.append,
                    min_zoom=args.min_zoom,
                    max_zoom=args.max_zoom,
                    assume_srid=args.assume_srid,
                    fix_geometry=args.fix_geometry,
                )
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
                failures += 1
                logger.error("Failed to load %s: %s", path, exc)
                logger.debug("traceback", exc_info=True)
                continue
            print(result.summary())

    if failures:
        logger.error("%d of %d file(s) failed", failures, len(paths))
        return 1
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    dsn = resolve_dsn(args.database_url)
    with _connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, title, geometry_type, feature_count, min_zoom, max_zoom "
            "FROM layers ORDER BY title"
        )
        rows = cur.fetchall()

    if not rows:
        print("No layers loaded yet. Try: geoplatform-etl load ./data")
        return 0

    header = f"{'NAME':<28} {'TITLE':<28} {'GEOMETRY':<14} {'FEATURES':>10}  ZOOM"
    print(header)
    print("-" * len(header))
    for name, title, geometry_type, count, min_zoom, max_zoom in rows:
        print(
            f"{name:<28} {title:<28} {(geometry_type or '-'):<14} "
            f"{count:>10}  {min_zoom}-{max_zoom}"
        )
    return 0


def cmd_drop(args: argparse.Namespace) -> int:
    if not args.yes:
        answer = input(f"Delete layer '{args.layer}' and all of its features? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Aborted.")
            return 1

    dsn = resolve_dsn(args.database_url)
    with _connect(dsn) as conn, conn.cursor() as cur:
        # ON DELETE CASCADE on features.layer_id takes the features with it.
        cur.execute("DELETE FROM layers WHERE name = %s RETURNING id", (args.layer,))
        deleted = cur.fetchone()

    if deleted is None:
        logger.error("No layer named %r", args.layer)
        return 1
    print(f"Deleted layer '{args.layer}'.")
    return 0


COMMANDS = {"load": cmd_load, "list": cmd_list, "drop": cmd_drop}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )
    return COMMANDS[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
