"""A very small Markdown -> HTML renderer, written here rather than added as a dependency.

WHY not a library: the site must render under a CSP that permits nothing off-origin and
the whole build has to stay reproducible from four pinned packages. A markdown dependency
would be the fifth, for a job that is ~300 lines of line-based parsing over documents we
control (METHODOLOGY.md, GOVERNANCE.md, research/*.md).

Deliberately partial. Supported: ATX headings, paragraphs, ordered/unordered lists with
one-level nesting, pipe tables (with alignment row), fenced and indented code, blockquotes,
thematic breaks, links, images, inline code, bold, italic, and footnotes. Not supported:
raw HTML passthrough (escaped), setext headings, reference links, nested blockquotes.

Output is written against the EU-CRI component sheet: tables become `.md-table` inside a
`.scroll-x`, fences become `pre.code`, blockquotes become `.callout`, footnote references
become `sup.fnref`, and the footnote list becomes a `.fnstrip`.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

__all__ = ["Document", "Heading", "render", "slugify"]

_FENCE_RE = re.compile(r"^(?P<fence>```|~~~)\s*(?P<lang>[\w+-]*)\s*$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL_RE = re.compile(r"^(?P<indent> *)(?P<bullet>[-*+])\s+(?P<text>.*)$")
_OL_RE = re.compile(r"^(?P<indent> *)(?P<num>\d{1,9})[.)]\s+(?P<text>.*)$")
_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^(?P<key>[^\]]+)\]:\s*(?P<text>.*)$")
_COMMENT_OPEN_RE = re.compile(r"^\s*<!--")
_NUMERIC_RE = re.compile(r"^[$€+\-±~<>=]*\s*\d[\d,]*(\.\d+)?\s*[%x×A-Za-z/$€]*$")

# Inline patterns, applied in this order. Code spans are extracted first and parked as
# placeholders so that emphasis and link syntax inside them is never interpreted.
_CODE_SPAN_RE = re.compile(r"(?P<ticks>`+)(?P<body>.+?)(?P=ticks)", re.DOTALL)
_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+\"(?P<title>[^\"]*)\")?\)")
_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)\s]+)(?:\s+\"(?P<title>[^\"]*)\")?\)")
_FOOTNOTE_REF_RE = re.compile(r"\[\^(?P<key>[^\]]+)\]")
_STRONG_RE = re.compile(r"\*\*(?!\s)(?P<body>.+?)(?<!\s)\*\*", re.DOTALL)
_STRONG_U_RE = re.compile(r"(?<![\w*])__(?!\s)(?P<body>.+?)(?<!\s)__(?![\w*])", re.DOTALL)
_EM_RE = re.compile(r"(?<![\w*])\*(?!\s)(?P<body>[^*]+?)(?<!\s)\*(?![\w*])")
# `_` only pairs at word boundaries: identifiers like min_gpu_count must survive intact.
_EM_U_RE = re.compile(r"(?<![\w_])_(?!\s)(?P<body>[^_]+?)(?<!\s)_(?![\w_])")
_PLACEHOLDER = "\x00CODE{}\x00"


@dataclass(frozen=True)
class Heading:
    """One heading, for building a table of contents."""

    level: int
    slug: str
    text: str


@dataclass
class Document:
    """Rendered markdown: the body HTML plus the structure a page shell needs."""

    html: str
    headings: list[Heading] = field(default_factory=list)
    title: str = ""
    lead: str = ""
    footnotes: int = 0


def slugify(text: str) -> str:
    """URL fragment for a heading. Stable across runs so deep links keep working."""
    clean = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_]+", "-", clean).strip("-") or "section"


def _plain(text: str) -> str:
    """Markdown source with its inline markers removed — plain text, never HTML."""
    text = _IMAGE_RE.sub(r"\g<alt>", text)
    text = _LINK_RE.sub(r"\g<text>", text)
    text = _FOOTNOTE_REF_RE.sub("", text)
    text = _CODE_SPAN_RE.sub(lambda m: m.group("body").strip(), text)
    return re.sub(r"(\*\*|__|[*_`])", "", text).strip()


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _safe_url(url: str) -> str:
    """Defuse anything that could execute.

    No escaping happens here: by the time links are substituted the whole line has already
    been through `_esc`, so `&` is `&amp;` and quotes are entities. Escaping twice was a
    real bug — `?b=1&c=2` came out as `&amp;amp;`.
    """
    if re.match(r"^\s*(javascript|data|vbscript):", url, re.IGNORECASE):
        return "#"
    return url


class _Inline:
    """Inline renderer. Stateful only in that it records which footnotes were referenced."""

    def __init__(self) -> None:
        self.refs: list[str] = []

    def __call__(self, text: str) -> str:
        spans: list[str] = []

        def park(m: re.Match[str]) -> str:
            spans.append(m.group("body").strip())
            return _PLACEHOLDER.format(len(spans) - 1)

        text = _CODE_SPAN_RE.sub(park, text)
        text = _esc(text)
        text = self._images(text)
        text = self._links(text)
        text = self._footnote_refs(text)
        text = _STRONG_RE.sub(r"<strong>\g<body></strong>", text)
        text = _STRONG_U_RE.sub(r"<strong>\g<body></strong>", text)
        text = _EM_RE.sub(r"<em>\g<body></em>", text)
        text = _EM_U_RE.sub(r"<em>\g<body></em>", text)
        for i, body in enumerate(spans):
            text = text.replace(
                _PLACEHOLDER.format(i), f'<code class="inline">{_esc(body)}</code>'
            )
        return text.replace("\\*", "*").replace("\\_", "_")

    @staticmethod
    def _images(text: str) -> str:
        """Relative images render; remote ones degrade to a link — no off-origin requests."""

        def sub(m: re.Match[str]) -> str:
            src, alt = m.group("src"), m.group("alt")
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//", src):
                return f'<a href="{_safe_url(src)}" rel="noopener">{alt or _safe_url(src)}</a>'
            return f'<img src="{_safe_url(src)}" alt="{alt}" loading="lazy">'

        return _IMAGE_RE.sub(sub, text)

    @staticmethod
    def _links(text: str) -> str:
        def sub(m: re.Match[str]) -> str:
            href = _safe_url(m.group("href"))
            title = f' title="{m.group("title")}"' if m.group("title") else ""
            external = bool(re.match(r"^https?:", m.group("href")))
            rel = ' rel="noopener"' if external else ""
            return f'<a href="{href}"{title}{rel}>{m.group("text")}</a>'

        return _LINK_RE.sub(sub, text)

    def _footnote_refs(self, text: str) -> str:
        def sub(m: re.Match[str]) -> str:
            key = m.group("key")
            if key not in self.refs:
                self.refs.append(key)
            n = self.refs.index(key) + 1
            return (
                f'<sup class="fnref" id="fnref-{_esc(key)}">'
                f'<a href="#fn-{_esc(key)}" aria-label="Footnote {n}">{n}</a></sup>'
            )

        return _FOOTNOTE_REF_RE.sub(sub, text)


class _Parser:
    def __init__(self, text: str, heading_offset: int) -> None:
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.i = 0
        self.offset = heading_offset
        self.out: list[str] = []
        self.headings: list[Heading] = []
        self.footnotes: dict[str, str] = {}
        self.inline = _Inline()
        self.title = ""
        self.lead = ""

    # -- helpers ----------------------------------------------------------------
    def _peek(self, ahead: int = 0) -> str | None:
        j = self.i + ahead
        return self.lines[j] if j < len(self.lines) else None

    def _slug(self, text: str) -> str:
        base = slugify(text)
        taken = {h.slug for h in self.headings}
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        return slug

    # -- driver -----------------------------------------------------------------
    def parse(self) -> Document:
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                self.i += 1
            elif _COMMENT_OPEN_RE.match(line):
                self._comment()
            elif _FENCE_RE.match(line):
                self._fence()
            elif _HEADING_RE.match(line):
                self._heading()
            elif _HR_RE.match(line) and not _UL_RE.match(line):
                self.out.append("<hr>")
                self.i += 1
            elif _FOOTNOTE_DEF_RE.match(line):
                self._footnote_def()
            elif line.startswith(">"):
                self._blockquote()
            elif self._is_table():
                self._table()
            elif (marker := _UL_RE.match(line) or _OL_RE.match(line)) is not None:
                self._list(len(marker.group("indent")))
            elif line.startswith("    "):
                self._indented_code()
            else:
                self._paragraph()

        if self.footnotes:
            self.out.append(self._render_footnotes())
        return Document(
            html="\n".join(self.out),
            headings=self.headings,
            title=self.title,
            lead=self.lead,
            footnotes=len(self.footnotes),
        )

    # -- blocks -----------------------------------------------------------------
    def _comment(self) -> None:
        while self.i < len(self.lines):
            closed = "-->" in self.lines[self.i]
            self.i += 1
            if closed:
                return

    def _fence(self) -> None:
        m = _FENCE_RE.match(self.lines[self.i])
        assert m is not None
        fence, lang = m.group("fence"), m.group("lang")
        self.i += 1
        body: list[str] = []
        while self.i < len(self.lines) and not self.lines[self.i].startswith(fence):
            body.append(self.lines[self.i])
            self.i += 1
        self.i += 1  # closing fence
        attr = f' data-lang="{_esc(lang)}"' if lang else ""
        self.out.append(f'<pre class="code"{attr}><code>{_esc(chr(10).join(body))}</code></pre>')

    def _indented_code(self) -> None:
        body: list[str] = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.startswith("    "):
                body.append(line[4:])
            elif not line.strip():
                body.append("")
            else:
                break
            self.i += 1
        while body and not body[-1].strip():
            body.pop()
        self.out.append(f'<pre class="code"><code>{_esc(chr(10).join(body))}</code></pre>')

    def _heading(self) -> None:
        m = _HEADING_RE.match(self.lines[self.i])
        assert m is not None
        self.i += 1
        raw = m.group("text")
        level = min(6, len(m.group("hashes")) + self.offset)
        plain = _plain(raw)
        slug = self._slug(plain)
        # Heading.text is PLAIN text, not HTML: callers put it through their own escaper
        # when they build a table of contents, and pre-escaped entities would double up.
        self.headings.append(Heading(level=level, slug=slug, text=plain))
        if not self.title and len(m.group("hashes")) == 1:
            self.title = plain
        self.out.append(f'<h{level} id="{slug}">{self.inline(raw)}</h{level}>')

    def _blockquote(self) -> None:
        body: list[str] = []
        while self.i < len(self.lines) and self.lines[self.i].startswith(">"):
            body.append(re.sub(r"^>\s?", "", self.lines[self.i]))
            self.i += 1
        inner = _Parser("\n".join(body), self.offset)
        inner.inline = self.inline
        rendered = inner.parse()
        self.out.append(f'<blockquote class="callout">{rendered.html}</blockquote>')

    def _footnote_def(self) -> None:
        m = _FOOTNOTE_DEF_RE.match(self.lines[self.i])
        assert m is not None
        self.i += 1
        parts = [m.group("text")]
        while self.i < len(self.lines) and self.lines[self.i].startswith("    "):
            parts.append(self.lines[self.i].strip())
            self.i += 1
        self.footnotes[m.group("key")] = self.inline(" ".join(p for p in parts if p))

    def _is_table(self) -> bool:
        head, delim = self._peek(), self._peek(1)
        return bool(
            head and delim and "|" in head and "|" in delim and _TABLE_DELIM_RE.match(delim)
        )

    def _table(self) -> None:
        def cells(row: str) -> list[str]:
            return [c.strip() for c in row.strip().strip("|").split("|")]

        head = cells(self.lines[self.i])
        aligns = [
            "right" if c.endswith(":") and not c.startswith(":")
            else "center" if c.startswith(":") and c.endswith(":")
            else ""
            for c in cells(self.lines[self.i + 1])
        ]
        self.i += 2
        rows: list[list[str]] = []
        while self.i < len(self.lines) and "|" in self.lines[self.i] and self.lines[self.i].strip():
            rows.append(cells(self.lines[self.i]))
            self.i += 1

        # A column of numbers is right-aligned and set in tabular mono even when the
        # source markdown says nothing about alignment — the house rule for numerals.
        # Emphasis is stripped first so a bolded figure still reads as a figure.
        def cell(c: int, r: list[str]) -> str:
            return _plain(r[c]) if c < len(r) else ""

        numeric = [
            all(
                _NUMERIC_RE.match(cell(c, r)) or cell(c, r) in ("", "-", "—", "n/a", "base")
                for r in rows
            )
            and any(_NUMERIC_RE.match(cell(c, r)) for r in rows)
            for c in range(len(head))
        ]

        def cls(c: int) -> str:
            right = numeric[c] or (c < len(aligns) and aligns[c] == "right")
            parts = (["num"] if numeric[c] else []) + (["ta-r"] if right else [])
            if c < len(aligns) and aligns[c] == "center":
                parts.append("ta-c")
            return f' class="{" ".join(parts)}"' if parts else ""

        html_rows = ["<thead><tr>"]
        html_rows += [
            f'<th scope="col"{cls(c)}>{self.inline(h)}</th>' for c, h in enumerate(head)
        ]
        html_rows.append("</tr></thead><tbody>")
        for row in rows:
            html_rows.append("<tr>")
            html_rows += [
                f"<td{cls(c)}>{self.inline(v)}</td>"
                for c, v in enumerate(row[: len(head)])
            ]
            html_rows.append("</tr>")
        html_rows.append("</tbody>")
        self.out.append(
            '<div class="scroll-x"><table class="md-table">'
            + "".join(html_rows)
            + "</table></div>"
        )

    def _list(self, indent: int) -> None:
        first = self.lines[self.i]
        ordered = bool(_OL_RE.match(first)) and not _UL_RE.match(first)
        tag = "ol" if ordered else "ul"
        items: list[str] = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            m = _OL_RE.match(line) if ordered else _UL_RE.match(line)
            other = _UL_RE.match(line) if ordered else _OL_RE.match(line)
            if not line.strip():
                nxt = self._peek(1)
                if nxt and (_UL_RE.match(nxt) or _OL_RE.match(nxt)):
                    self.i += 1
                    continue
                break
            if m is None or len(m.group("indent")) < indent:
                if other is not None and len(other.group("indent")) >= indent:
                    break  # a sibling list of the other kind: close this one
                break
            if len(m.group("indent")) > indent:
                nested = self._capture_nested(len(m.group("indent")))
                if items:
                    items[-1] += nested
                continue
            parts = [m.group("text")]
            self.i += 1
            # Lazy continuation: an unindented, non-marker line belongs to this item.
            while self.i < len(self.lines):
                nxt = self.lines[self.i]
                if not nxt.strip() or _UL_RE.match(nxt) or _OL_RE.match(nxt):
                    break
                if _HEADING_RE.match(nxt) or _FENCE_RE.match(nxt) or nxt.startswith(">"):
                    break
                parts.append(nxt.strip())
                self.i += 1
            items.append(f"<li>{self.inline(' '.join(parts))}")
        self.out.append(f"<{tag}>" + "".join(f"{it}</li>" for it in items) + f"</{tag}>")

    def _capture_nested(self, indent: int) -> str:
        """Render a deeper-indented run as a child list of the item above it."""
        start = self.i
        while self.i < len(self.lines):
            line = self.lines[self.i]
            m = _UL_RE.match(line) or _OL_RE.match(line)
            if not line.strip() or m is None or len(m.group("indent")) < indent:
                break
            self.i += 1
        block = "\n".join(x[indent:] if len(x) > indent else x for x in self.lines[start : self.i])
        inner = _Parser(block, self.offset)
        inner.inline = self.inline
        return inner.parse().html

    def _paragraph(self) -> None:
        parts: list[str] = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip() or _HEADING_RE.match(line) or _FENCE_RE.match(line):
                break
            if _HR_RE.match(line) or line.startswith(">") or _COMMENT_OPEN_RE.match(line):
                break
            if _UL_RE.match(line) or _OL_RE.match(line) or self._is_table():
                break
            parts.append(line.strip())
            self.i += 1
        text = " ".join(parts)
        if not text:
            return
        if not self.lead and self.title:
            self.lead = _plain(text)  # plain, for the same reason as Heading.text
        self.out.append(f"<p>{self.inline(text)}</p>")

    def _render_footnotes(self) -> str:
        order = [k for k in self.inline.refs if k in self.footnotes]
        order += [k for k in self.footnotes if k not in order]
        items = "".join(
            f'<li id="fn-{_esc(k)}"><span class="num">{n}</span>'
            f'<span>{self.footnotes[k]} <a href="#fnref-{_esc(k)}"'
            f' aria-label="Back to reference {n}">&#8617;</a></span></li>'
            for n, k in enumerate(order, start=1)
        )
        return (
            '<aside class="fnstrip" aria-label="Footnotes">'
            '<h3 class="fnstrip__h">Notes</h3>'
            f'<ol class="fnstrip__list">{items}</ol></aside>'
        )


def render(text: str, *, heading_offset: int = 0) -> Document:
    """Render markdown to component-sheet HTML.

    `heading_offset` demotes every heading by N levels, so a document whose own `#` is the
    page title can be dropped into a page that already owns the single `<h1>`.
    """
    return _Parser(text, heading_offset).parse()
