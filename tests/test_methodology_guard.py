# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""The methodology change guard, verified locally and in CI.

Three invariants:
1. The working tree's methodology hash matches METHODOLOGY.lock (no silent drift).
2. The lock's version matches config/factors.yaml.
3. CHANGELOG.md contains an entry for the current version.
Plus: the lock generator refuses a changed hash under an unchanged released version.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from eucri import methodology
from eucri.config import load_factors

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_lock_matches_working_tree() -> None:
    lock = methodology.read_lock()
    assert lock is not None, "METHODOLOGY.lock missing — run: python -m eucri.run docs"
    assert lock["current"]["hash"] == methodology.compute_hash(), (
        "Methodology files changed without regenerating the lock. Follow GOVERNANCE.md §1:"
        " bump methodology_version, add a CHANGELOG entry, run `python -m eucri.run docs`."
    )


def test_lock_version_matches_config() -> None:
    lock = methodology.read_lock()
    assert lock is not None
    assert lock["current"]["version"] == load_factors().methodology_version


def test_changelog_has_current_version() -> None:
    version = load_factors().methodology_version
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {version}" in changelog, f"CHANGELOG.md has no entry for {version}"


def _make_repo(tmp_path: Path, version: str) -> Path:
    (tmp_path / "config" / "providers").mkdir(parents=True)
    src = REPO_ROOT / "config"
    factors = (src / "factors.yaml").read_text(encoding="utf-8")
    current = load_factors().methodology_version
    factors = factors.replace(
        f'methodology_version: "{current}"', f'methodology_version: "{version}"'
    )
    (tmp_path / "config" / "factors.yaml").write_text(factors, encoding="utf-8")
    shutil.copy(src / "sovereign.yaml", tmp_path / "config" / "sovereign.yaml")
    return tmp_path


def test_generator_refuses_unversioned_change_when_released(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, "1.0.0")
    methodology.update_lock(root)  # baseline lock
    factors = root / "config" / "factors.yaml"
    factors.write_text(
        factors.read_text(encoding="utf-8").replace("min_providers: 5", "min_providers: 3"),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="Bump methodology_version"):
        methodology.update_lock(root)


def test_generator_allows_change_under_dev_version(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, "1.1.0-dev")
    methodology.update_lock(root)
    factors = root / "config" / "factors.yaml"
    factors.write_text(
        factors.read_text(encoding="utf-8").replace("min_providers: 5", "min_providers: 3"),
        encoding="utf-8",
    )
    lock = methodology.update_lock(root)  # must not raise
    assert len(lock["history"]) == 2


def test_generator_allows_change_with_version_bump(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, "1.0.0")
    methodology.update_lock(root)
    factors = root / "config" / "factors.yaml"
    text = factors.read_text(encoding="utf-8")
    text = text.replace("min_providers: 5", "min_providers: 3")
    text = text.replace('methodology_version: "1.0.0"', 'methodology_version: "1.1.0"')
    factors.write_text(text, encoding="utf-8")
    lock = methodology.update_lock(root)
    assert lock["current"]["version"] == "1.1.0"
