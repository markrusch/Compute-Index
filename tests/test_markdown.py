# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""The in-repo Markdown renderer. Covers the constructs METHODOLOGY.md, GOVERNANCE.md and
the research notes actually use, plus the escaping rules that keep the output safe."""

from __future__ import annotations

from eucri.outputs.markdown import render, slugify


def test_headings_get_stable_slugs_and_plain_text():
    doc = render("# Title\n\n## 3. Aggregation (exact algorithm)\n")
    assert '<h1 id="title">Title</h1>' in doc.html
    assert 'id="3-aggregation-exact-algorithm"' in doc.html
    assert doc.title == "Title"
    # Heading.text is PLAIN, so a caller escaping it does not double-escape entities.
    assert [h.text for h in doc.headings] == ["Title", "3. Aggregation (exact algorithm)"]


def test_heading_offset_demotes_every_level():
    doc = render("# Doc\n\n## Section\n\n### Sub\n", heading_offset=1)
    assert "<h2 id=\"doc\">Doc</h2>" in doc.html
    assert "<h3 id=\"section\">Section</h3>" in doc.html
    assert "<h4 id=\"sub\">Sub</h4>" in doc.html
    assert [h.level for h in doc.headings] == [2, 3, 4]


def test_duplicate_headings_get_distinct_slugs():
    doc = render("## Notes\n\n## Notes\n")
    assert [h.slug for h in doc.headings] == ["notes", "notes-2"]


def test_paragraphs_join_wrapped_lines():
    doc = render("one line\nsecond line\n\nnew para\n")
    assert doc.html == "<p>one line second line</p>\n<p>new para</p>"


def test_emphasis_and_inline_code():
    doc = render("**bold** and *italic* and `code`\n")
    assert "<strong>bold</strong>" in doc.html
    assert "<em>italic</em>" in doc.html
    assert '<code class="inline">code</code>' in doc.html


def test_underscores_inside_identifiers_are_not_emphasis():
    """`min_gpu_count` in prose must survive: this is the single most likely regression."""
    doc = render("the min_gpu_count and max_weight_share_pct parameters\n")
    assert "<em>" not in doc.html
    assert "min_gpu_count" in doc.html


def test_emphasis_inside_a_code_span_is_not_interpreted():
    doc = render("`a_b_c **x**`\n")
    assert "<em>" not in doc.html and "<strong>" not in doc.html
    assert "a_b_c **x**" in doc.html


def test_links_and_html_escaping():
    doc = render('[EU-CRI](https://example.org/a?b=1&c=2) and <script>alert(1)</script>\n')
    assert 'href="https://example.org/a?b=1&amp;c=2"' in doc.html
    assert 'rel="noopener"' in doc.html
    assert "<script>" not in doc.html
    assert "&lt;script&gt;" in doc.html


def test_javascript_urls_are_defused():
    doc = render("[x](javascript:alert(1))\n")
    assert "javascript:" not in doc.html
    assert 'href="#"' in doc.html


def test_remote_images_degrade_to_links_and_local_ones_render():
    remote = render("![alt](https://cdn.example.com/x.png)\n")
    assert "<img" not in remote.html  # no off-origin request, ever
    assert "<a href=" in remote.html
    local = render("![alt](charts/headline.png)\n")
    assert '<img src="charts/headline.png" alt="alt"' in local.html


def test_unordered_and_ordered_lists_with_lazy_continuation():
    doc = render(
        "- first item\n  wrapped onto a second line\n- second item\n\n"
        "1. step one\n2. step two\n"
    )
    assert "<ul><li>first item wrapped onto a second line</li><li>second item</li></ul>" \
        in doc.html
    assert "<ol><li>step one</li><li>step two</li></ol>" in doc.html


def test_nested_list_becomes_a_child_list():
    doc = render("- outer\n    - inner\n- outer two\n")
    assert "<ul>" in doc.html
    assert doc.html.count("<ul>") == 2
    assert "inner" in doc.html


def test_fenced_code_is_escaped_and_keeps_its_language():
    doc = render("```bash\ngit clone x && cd <y>\n```\n")
    assert '<pre class="code" data-lang="bash">' in doc.html
    assert "&lt;y&gt;" in doc.html
    assert "&amp;&amp;" in doc.html


def test_indented_code_block():
    doc = render("text\n\n    python -m eucri.run constituents\n\nmore\n")
    assert '<pre class="code"><code>python -m eucri.run constituents</code></pre>' in doc.html


def test_blockquote_becomes_a_callout():
    doc = render("> a **warning** line\n> continued\n")
    assert '<blockquote class="callout">' in doc.html
    assert "<strong>warning</strong>" in doc.html


def test_thematic_break():
    assert "<hr>" in render("a\n\n---\n\nb\n").html


def test_table_renders_in_a_scroll_container_with_scoped_headers():
    doc = render("| a | b |\n|---|---|\n| x | y |\n")
    assert '<div class="scroll-x"><table class="md-table">' in doc.html
    assert '<th scope="col"' in doc.html
    assert "<td>x</td>" in doc.html


def test_numeric_table_columns_are_right_aligned_tabular():
    doc = render(
        "| provider | price | note |\n|---|---|---|\n"
        "| aws | 7.3616 | list |\n| **runpod** | **3.29** | executable |\n"
    )
    # the numeric column gets .num (mono/tabular) and .ta-r; the text columns do not
    assert '<td class="num ta-r">7.3616</td>' in doc.html
    assert "<td>list</td>" in doc.html
    assert '<td class="num ta-r"><strong>3.29</strong></td>' in doc.html


def test_explicit_right_alignment_row_is_honoured():
    doc = render("| a | b |\n|---|---:|\n| x | text |\n")
    assert '<td class="ta-r">text</td>' in doc.html


def test_table_delimiter_row_is_not_mistaken_for_a_rule():
    assert "<hr>" not in render("| a |\n|---|\n| 1 |\n").html


def test_footnotes_link_both_ways_and_render_a_note_strip():
    doc = render("claim[^a] and another[^b]\n\n[^a]: first note\n[^b]: second note\n")
    assert '<sup class="fnref" id="fnref-a"><a href="#fn-a"' in doc.html
    assert '<li id="fn-a">' in doc.html
    assert 'href="#fnref-a"' in doc.html
    assert '<aside class="fnstrip"' in doc.html
    assert doc.footnotes == 2


def test_html_comments_are_dropped_including_multiline():
    doc = render("<!-- AUTO-GENERATED\n     do not edit -->\n\n# Real\n")
    assert "AUTO-GENERATED" not in doc.html
    assert doc.title == "Real"


def test_lead_is_the_first_paragraph_as_plain_text():
    doc = render("# T\n\n**A bold dek** with `code`\n\nsecond para\n")
    assert doc.lead == "A bold dek with code"


def test_slugify_is_url_safe():
    assert slugify("3.1 Continuity — series!") == "31-continuity-series"
    assert slugify("!!!") == "section"
