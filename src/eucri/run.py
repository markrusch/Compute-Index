"""CLI entrypoint: python -m eucri.run <command>."""

from __future__ import annotations

import argparse
import logging
import sys

log = logging.getLogger("eucri")


def _cmd_migrate(args: argparse.Namespace) -> int:
    from eucri import db

    conn = db.connect()
    applied = db.migrate(conn)
    print(f"applied: {applied or 'nothing (up to date)'}")
    return 0


def _cmd_docs(args: argparse.Namespace) -> int:
    from eucri import methodology

    methodology.generate()
    print("METHODOLOGY.md and METHODOLOGY.lock regenerated.")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(prog="eucri", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply pending database migrations")
    sub.add_parser("docs", help="regenerate METHODOLOGY.md and METHODOLOGY.lock")

    p_daily = sub.add_parser("daily", help="collect + compute + export for a UTC date")
    p_daily.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")

    p_cons = sub.add_parser("constituents", help="audit table for a print")
    p_cons.add_argument("--date", required=True)
    p_cons.add_argument("--series", default="EU-CRI-H100")

    p_back = sub.add_parser("backfill", help="recompute index range from stored observations")
    p_back.add_argument("--from", dest="date_from", required=True)
    p_back.add_argument("--to", dest="date_to", required=True)

    sub.add_parser("validate", help="source-dropout sensitivity + check-series correlation")
    sub.add_parser("post", help="regenerate substack_post.md")

    args = parser.parse_args(argv)

    if args.command == "migrate":
        return _cmd_migrate(args)
    if args.command == "docs":
        return _cmd_docs(args)
    if args.command in {"daily", "constituents", "backfill", "validate", "post"}:
        from eucri import commands

        return commands.dispatch(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
