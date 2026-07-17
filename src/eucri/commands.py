"""Implementations of the data-facing CLI commands (daily, constituents, ...)."""

from __future__ import annotations

import argparse


def dispatch(args: argparse.Namespace) -> int:
    raise SystemExit(f"command {args.command!r} is not implemented yet (Phase 1)")
