"""Static site generation: revision selection, gap honesty, and the page shell contract."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from eucri import db
from eucri.outputs import site, webdata
from tests.conftest import insert_run

PAGES = (
    "index.html", "methodology.html", "governance.html", "research.html",
)


def _print(
    conn: sqlite3.Connection,
    date: str,
    series: str,
    revision: int,
    value: float | None,
    *,
    flags: str = "",
    n_sources: int = 5,
    n_executable: int = 1,
    run_id: str = "r1",
) -> None:
    conn.execute(
        "INSERT INTO daily_index (date, series, revision, value_usd, value_eur, fx_rate,"
        " fx_date, n_sources, n_executable, flags, methodology_version, computed_at, run_id)"
        " VALUES (?, ?, ?, ?, ?, 1.1, ?, ?, ?, ?, '0.3.0-dev', ?, ?)",
        (date, series, revision, value, None if value is None else value / 1.1,
         date, n_sources, n_executable, flags, db.utc_now_iso(), run_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# max revision per (date, series) — the single read rule the whole site depends on
# ---------------------------------------------------------------------------


def test_series_history_takes_the_max_revision_per_date_and_series(conn):
    insert_run(conn, "r1", "2026-08-01")
    # rev 1 said 3.00; rev 2 corrected it to 3.50. Only rev 2 may ever be published.
    _print(conn, "2026-08-01", "EU-CRI-H100", 1, 3.00)
    _print(conn, "2026-08-01", "EU-CRI-H100", 2, 3.50, flags="correction")
    _print(conn, "2026-08-02", "EU-CRI-H100", 1, 3.60)

    history = site.series_history(conn, "EU-CRI-H100")

    assert [(p.date, p.value) for p in history] == [
        ("2026-08-01", 3.50),
        ("2026-08-02", 3.60),
    ]
    assert history[0].flags == "correction"


def test_max_revision_withdrawal_to_a_gap_is_respected(conn):
    """A correction that withdraws a value must leave a GAP, not resurrect revision 1."""
    insert_run(conn, "r1", "2026-08-01")
    _print(conn, "2026-08-01", "EU-CRI-H100", 1, 3.00)
    _print(conn, "2026-08-01", "EU-CRI-H100", 2, None, flags="insufficient_sources,correction")

    history = site.series_history(conn, "EU-CRI-H100")

    assert len(history) == 1
    assert history[0].value is None


def test_series_history_does_not_leak_other_series(conn):
    insert_run(conn, "r1", "2026-08-01")
    _print(conn, "2026-08-01", "EU-CRI-H100", 1, 3.00)
    _print(conn, "2026-08-01", "EU-CRI-A100", 3, 1.00)

    assert [p.value for p in site.series_history(conn, "EU-CRI-H100")] == [3.00]
    assert [p.value for p in site.series_history(conn, "EU-CRI-A100")] == [1.00]


def test_series_history_honours_the_since_bound(conn):
    insert_run(conn, "r1", "2026-08-01")
    for day, value in (("2026-07-30", 1.0), ("2026-08-01", 2.0), ("2026-08-02", 3.0)):
        _print(conn, day, "EU-CRI-H100", 1, value)

    assert [p.date for p in site.series_history(conn, "EU-CRI-H100", since="2026-08-01")] == [
        "2026-08-01", "2026-08-02"
    ]


def test_previous_published_skips_gaps_and_stale_revisions(conn):
    insert_run(conn, "r1", "2026-08-01")
    _print(conn, "2026-08-01", "EU-CRI-H100", 1, 3.10)
    _print(conn, "2026-08-02", "EU-CRI-H100", 1, 3.20)
    _print(conn, "2026-08-02", "EU-CRI-H100", 2, None, flags="insufficient_sources")
    _print(conn, "2026-08-03", "EU-CRI-H100", 1, 3.30)

    # 08-02 was withdrawn at rev 2, so the prior published print is 08-01, not 3.20.
    assert site.previous_published(conn, "EU-CRI-H100", "2026-08-03") == ("2026-08-01", 3.10)


# ---------------------------------------------------------------------------
# window alignment and gaps
# ---------------------------------------------------------------------------


def test_window_is_a_full_calendar_range_ending_on_the_date():
    window = site._window("2026-08-16", 5)
    assert window == [
        "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15", "2026-08-16"
    ]


def test_windowed_fills_absent_days_as_gaps():
    points = [site.Point("2026-08-16", 3.29)]
    filled = site._windowed(points, site._window("2026-08-16", 3))

    assert [p.value for p in filled] == [None, None, 3.29]
    assert filled[0].flags == "no_print"


# ---------------------------------------------------------------------------
# chart: never interpolate across a missing print
# ---------------------------------------------------------------------------


def test_chart_breaks_the_line_across_a_gap():
    contiguous = site.line_chart(
        [site.Point(f"2026-08-0{d}", 3.0 + d / 10) for d in (1, 2, 3)],
        symbol="X",
    )
    gapped = site.line_chart(
        [
            site.Point("2026-08-01", 3.1),
            site.Point("2026-08-02", None),
            site.Point("2026-08-03", 3.3),
        ],
        symbol="X",
    )
    assert contiguous.count('class="ch-line"') == 1
    # no path may span the gap; the two survivors are drawn as isolated points instead
    assert 'class="ch-line"' not in gapped
    assert gapped.count('class="ch-gapmark"') == 1
    assert "1 published, 2 gapped" not in gapped and "2 published, 1 gapped" in gapped


def test_chart_with_no_published_value_says_so_instead_of_drawing():
    out = site.line_chart([site.Point("2026-08-01", None)], symbol="EU-CRI-H200")
    assert "gapnote" in out
    assert "<svg class=\"chart\"" not in out
    assert 'class="ch-line"' not in out


def test_chart_marks_exactly_one_current_value():
    out = site.line_chart(
        [site.Point(f"2026-08-0{d}", 3.0 + d / 10) for d in (1, 2, 3)], symbol="X"
    )
    assert out.count('class="ch-marker"') == 1
    assert out.count('class="ch-marker-rule"') == 1


def test_sparkline_needs_two_points():
    assert site.sparkline([site.Point("2026-08-01", 3.0)]) == ""
    assert "<svg" in site.sparkline(
        [site.Point("2026-08-01", 3.0), site.Point("2026-08-02", 3.1)]
    )


# ---------------------------------------------------------------------------
# whole-site generation
# ---------------------------------------------------------------------------


@pytest.fixture()
def built(conn, tmp_path, monkeypatch) -> Path:
    out = tmp_path / "site"
    (out / "assets").mkdir(parents=True)
    for name in ("tokens.css", "site.css"):
        (out / "assets" / name).write_text(
            (site.ASSETS / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    research = tmp_path / "research"
    research.mkdir()
    (research / "a-note.md").write_text(
        "# A note title\n\n**The dek line.**\n\n16 August 2026\n\n## One\n\ntext\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(site, "SITE_DIR", out)
    monkeypatch.setattr(site, "ASSETS", out / "assets")
    monkeypatch.setattr(site, "RESEARCH_SRC", research)

    insert_run(conn, "r1", "2026-08-16")
    _print(conn, "2026-08-10", "EU-CRI-H100", 1, 3.25)
    _print(conn, "2026-08-16", "EU-CRI-H100", 1, 3.29)
    _print(conn, "2026-08-16", "EU-CRI-H200", 1, None, flags="insufficient_sources",
           n_sources=0, n_executable=0)
    conn.executemany(
        "INSERT INTO constituents (date, series, revision, provider, source, tier,"
        " price_usd, weight, included, exclusion_reason, flags) VALUES"
        " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("2026-08-16", "EU-CRI-H100", 1, "runpod", "runpod", "executable", 3.29,
             25.0, 1, None, "weight_capped"),
            ("2026-08-16", "EU-CRI-H100", 1, "seeweb", "static_yaml", "list", 2.16,
             18.75, 1, "trimmed", ""),
            ("2026-08-16", "EU-CRI-H100", 1, "aws", "", "", 0.0, 0.0, 0,
             "out_of_population", ""),
        ],
    )
    conn.commit()
    site.generate(conn)
    return out


def test_generate_writes_every_page(built):
    for name in PAGES:
        assert (built / name).exists(), name
    assert (built / "research" / "a-note.html").exists()


def test_pages_are_self_contained(built):
    """No off-origin request is possible: no stylesheet link, no script src, no @import,
    no url() that resolves anywhere. Prose that merely mentions the words is allowed."""
    for name in PAGES:
        html = (built / name).read_text(encoding="utf-8")
        assert '<link rel="stylesheet"' not in html
        assert "<script src=" not in html
        assert not re.search(r"@import\s+(url\(|[\"'])", html)
        assert not re.search(r"\burl\(\s*['\"]?(https?:)?//", html)
        assert "<style>" in html  # tokens + components are inlined


def test_pages_carry_one_h1_and_a_current_nav_marker(built):
    for name in PAGES:
        html = (built / name).read_text(encoding="utf-8")
        body = html.split("</style>", 1)[1]  # the CSS mentions the attribute in a selector
        assert body.count("<h1") == 1, name
        assert body.count('aria-current="page"') == 1, name


def test_theming_contract_is_present_on_every_page(built):
    for name in PAGES:
        css = (built / name).read_text(encoding="utf-8")
        assert "@media (prefers-color-scheme: dark)" in css
        assert ':root:not([data-theme="light"])' in css
        assert ':root[data-theme="dark"]' in css
        assert "background: var(--page)" in css


def test_dashboard_shows_the_headline_and_never_carries_a_gap_forward(built):
    html = (built / "index.html").read_text(encoding="utf-8")
    assert "3.29" in html
    # the gapped sub-index shows a dash and the reason, not the last good value
    assert "below the provider gate" in html
    assert "H200" in html


def test_live_surfaces_never_show_a_stale_print_as_current(conn):
    """A series that stops being computed must vanish from the live surfaces, not keep
    rendering its last good value.

    Regression: EU-CRI-H100-CLOUD was retired in v0.3.0 but left in site.TICKER, so the
    ticker went on showing 3.85 from 2026-08-15 under methodology 0.2.0-dev. On
    2026-09-04 it was the only number on a ticker where every live series was honestly
    gapped -- precisely the "stale value dressed as live" this generator exists to
    prevent.
    """
    insert_run(conn, "r1", "2026-08-16")
    session = "2026-08-16"
    # A series still being computed, gapped this session after an earlier real value.
    _print(conn, "2026-08-10", "EU-CRI-H100", 1, 3.85)
    _print(conn, "2026-08-16", "EU-CRI-H100", 1, None, flags="insufficient_sources",
           n_sources=4, n_executable=0)
    # A retired series: its newest row is old, and it must not resolve as current.
    _print(conn, "2026-08-10", "EU-CRI-RETIRED", 1, 3.85)

    assert site.latest_print(conn, "EU-CRI-RETIRED")["value_usd"] == 3.85
    assert site.current_print(conn, "EU-CRI-RETIRED", session) is None
    # A live series keeps resolving, and its gap stays a gap rather than reverting to 3.85.
    assert site.current_print(conn, "EU-CRI-H100", session)["value_usd"] is None

    # And the retired series is gone from every surface that renders live values.
    assert "EU-CRI-H100-CLOUD" not in site.TICKER
    assert "EU-CRI-H100-CLOUD" not in site.SERIES_LABEL
    assert "EU-CRI-H100-CLOUD" not in webdata.ALL_SERIES


def test_research_note_is_rendered_from_markdown(built):
    html = (built / "research" / "a-note.html").read_text(encoding="utf-8")
    assert "A note title" in html
    assert "The dek line." in html
    assert "Content slot" not in html
    index = (built / "research.html").read_text(encoding="utf-8")
    assert 'href="research/a-note.html"' in index
    assert "16 Aug 2026" in index  # date sniffed from the byline, no front matter needed


def test_planned_note_without_copy_gets_a_marked_slot(built):
    html = (built / "research" / "composition-vs-price.html").read_text(encoding="utf-8")
    assert "Content slot" in html
    assert "has not been written yet" in html


def test_methodology_ledger_is_read_from_config(built):
    html = (built / "methodology.html").read_text(encoding="utf-8")
    assert "Publication gate" in html
    assert "Concentration cap" in html
    assert "sha256:" in html
    assert "ledger__row" in html


def test_front_matter_is_optional_and_parsed_when_present():
    meta, body = site._front_matter("---\ntitle: T\ndate: 2026-01-02\n---\n\n# H\n")
    # PyYAML types a bare date; the generator stringifies it, so both forms are fine.
    assert meta["title"] == "T"
    assert str(meta["date"]) == "2026-01-02"
    assert body.startswith("# H")
    assert site._front_matter("# H\n") == ({}, "# H\n")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("byline 2026-08-16 here", "2026-08-16"),
        ("EU-CRI Research Note 2026-01 · 16 August 2026 · Mark Rusch", "2026-08-16"),
        ("no date at all", ""),
    ],
)
def test_sniff_date(text, expected):
    assert site._sniff_date(text) == expected


def test_note_masthead_is_not_rendered_twice():
    """The page header publishes title + dek + byline; the body must not repeat them."""
    body = _strip_note_masthead_fixture()
    assert body.startswith("## Abstract")
    assert "Title here" not in body
    assert "The dek." not in body
    assert "Mark Rusch" not in body


def _strip_note_masthead_fixture() -> str:
    return site._strip_note_masthead(
        "# Title here\n\n**The dek.**\n\nNote 2026-01 · 16 August 2026 · Mark Rusch\n\n"
        "---\n\n## Abstract\n\nbody text\n"
    )


def test_note_without_a_rule_only_loses_its_h1():
    out = site._strip_note_masthead("# Title\n\nintro paragraph\n\n## One\n")
    assert out == "intro paragraph\n\n## One\n"


def test_note_without_an_h1_is_untouched():
    assert site._strip_note_masthead("## One\n\ntext\n") == "## One\n\ntext\n"
