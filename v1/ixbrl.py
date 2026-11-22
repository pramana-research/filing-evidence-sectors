"""Read an inline-XBRL filing (10-K / 10-Q HTML) into numbered pages of text plus its tagged facts.

Each displayed `ix:nonFraction` fact carries its concept, its value (after the `scale`, `sign` and
`format` attributes), unit, period, dimensions, and every place it's displayed: page number and
rendered line. That gives an answer key with exact locations, straight from the filer.

Rendering rules (fixed, documented in PROTOCOL.md §5):
  - page breaks: CSS `page-break-before/after: always` or `break-before/after: page` on any element;
  - block elements end a line, except inside a table cell (cell contents wrapped in <div>/<p> stay on
    the row's line); table rows end a line; table cells are separated by two spaces;
  - whitespace inside a line is collapsed; empty lines are dropped;
  - a page longer than ~3,000 tokens (no page-break markup, or e.g. an exhibit index) is split at line
    boundaries into parts of ~1,500 tokens (MAX_PAGE_CHARS / SPLIT_PAGE_CHARS);
  - content inside `ix:header` (hidden facts, contexts, units) is never rendered.

Standard library only (html.parser, xml.etree), so it runs anywhere.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser

BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "tr",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "hr",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "section",
    "article",
    "header",
    "footer",
    "blockquote",
    "pre",
}
CELL_TAGS = {"td", "th"}
VOID_TAGS = {"br", "hr", "img", "meta", "link", "input", "col", "area", "base", "wbr"}
SKIP_TEXT_TAGS = {"script", "style", "title"}

# Private-use characters mark where a fact's displayed text starts and ends while rendering;
# they're removed from the final page text.
_FACT_START, _FACT_SEP, _FACT_END = "", "", ""
_MARKER = re.compile(f"{_FACT_START}(\\d+){_FACT_SEP}|{_FACT_END}")

_WORD_NUMBERS = {
    "no": 0,
    "none": 0,
    "zero": 0,
    "nil": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


@dataclass
class Context:
    id: str
    start: str | None = None  # duration contexts
    end: str | None = None
    instant: str | None = None  # point-in-time contexts
    dims: dict[str, str] = field(default_factory=dict)  # dimension qname -> member qname (or typed value)

    @property
    def period_end(self) -> str | None:
        return self.end or self.instant


@dataclass
class Occurrence:
    page: int
    line: str  # the rendered line containing the displayed number


@dataclass
class Fact:
    id: str  # stable within the filing: f<index> in document order
    concept: str  # e.g. us-gaap:NetIncomeLoss
    context: str
    unit: str | None  # e.g. iso4217:USD, shares, iso4217:USD/shares, xbrli:pure
    value: float  # numeric value, scale and sign applied
    display: str  # the text as shown in the filing, e.g. "15,511"
    scale: int
    decimals: str | None
    occurrences: list[Occurrence] = field(default_factory=list)


@dataclass
class Filing:
    pages: list[str]
    facts: list[Fact]
    contexts: dict[str, Context]
    units: dict[str, str]
    skipped: dict[str, int] = field(default_factory=dict)  # why some tagged facts weren't kept, with counts
    split_pages: int = 0  # rendered pages too long to show whole, split into parts (see MAX_PAGE_CHARS)


def parse_number(text: str, fmt: str | None) -> float | None:
    """Apply an inline-XBRL `format` transform to displayed text. Returns None if it can't be read."""
    t = text.strip()
    f = (fmt or "").split(":")[-1].lower().replace("-", "")
    if f in ("fixedzero", "zerodash", "zerodash2", "fixedempty") or t in ("—", "–", "-"):
        return 0.0
    if f in ("numwordsen", "numwordsenregular") or t.lower() in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[t.lower()]) if t.lower() in _WORD_NUMBERS else None
    if f in ("numcommadecimal", "numdotcomma"):  # 1.234,56
        t = t.replace(".", "").replace(" ", "").replace(",", ".")
    else:  # num-dot-decimal and default: 1,234.56
        t = t.replace(",", "").replace(" ", "")
    t = t.replace("$", "").replace("(", "").replace(")", "")
    try:
        return float(t)
    except ValueError:
        return None


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pages: list[str] = []
        self.buf: list[str] = []
        self.stack: list[tuple[str, bool]] = []  # (tag, page break after this element closes)
        self.hidden = 0  # depth inside ix:header
        self.skip_text = 0  # depth inside script/style/title
        self.raw_facts: list[dict] = []
        self.fact_stack: list[dict] = []  # open ix:nonfraction tags (nesting is legal)
        self.contexts: dict[str, Context] = {}
        self.units: dict[str, str] = {}
        self._ctx: Context | None = None
        self._ctx_field: str | None = None
        self._member_dim: str | None = None
        self._unit: dict | None = None
        self._measure_target: str | None = None

    # -- pages --------------------------------------------------------------------------------------
    def _new_page(self):
        self.pages.append("".join(self.buf))
        self.buf = []

    def _in_cell(self) -> bool:
        """True when the innermost open table element is a cell: block tags there don't break the line,
        so a row whose cells wrap their content in <div>/<p> still renders as one line."""
        for t, _ in reversed(self.stack):
            if t in CELL_TAGS:
                return True
            if t in ("tr", "table"):
                return False
        return False

    def _block_break(self, tag: str) -> str:
        return " " if self._in_cell() and tag not in ("tr", "table") else "\n"

    @staticmethod
    def _breaks(style: str) -> tuple[bool, bool]:
        s = style.replace(" ", "").lower()
        before = "page-break-before:always" in s or "break-before:page" in s
        after = "page-break-after:always" in s or "break-after:page" in s
        return before, after

    # -- parser callbacks ---------------------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        before, after = self._breaks(a.get("style", ""))
        if before and not self.hidden:
            self._new_page()
        if tag == "ix:header":
            self.hidden += 1
        if tag in SKIP_TEXT_TAGS:
            self.skip_text += 1
        self._metadata_start(tag, a)
        if tag == "ix:nonfraction":
            fact = {
                **a,
                "text": "",
                "index": len(self.raw_facts) + len(self.fact_stack),
                "hidden": bool(self.hidden),
            }
            self.fact_stack.append(fact)
            if not self.hidden:
                self.buf.append(f"{_FACT_START}{fact['index']}{_FACT_SEP}")
        if not self.hidden:
            if tag in BLOCK_TAGS:
                self.buf.append(self._block_break(tag))
            elif tag in CELL_TAGS:
                self.buf.append("  ")
        if tag in VOID_TAGS:
            if after and not self.hidden:
                self._new_page()
        else:
            self.stack.append((tag, after))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:  # <div/> written self-closing: close it now
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        after = False
        # pop up to the matching open tag (HTML in filings is usually well formed; be tolerant if not)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                after = any(b for _, b in self.stack[i:])
                del self.stack[i:]
                break
        else:
            if tag in VOID_TAGS:
                return
        if tag == "ix:nonfraction" and self.fact_stack:
            fact = self.fact_stack.pop()
            self.raw_facts.append(fact)
            if not self.hidden:
                self.buf.append(_FACT_END)
        self._metadata_end(tag)
        if not self.hidden and tag in BLOCK_TAGS:
            self.buf.append(self._block_break(tag))
        if tag == "ix:header":
            self.hidden -= 1
        if tag in SKIP_TEXT_TAGS:
            self.skip_text -= 1
        if after and not self.hidden:
            self._new_page()

    def handle_data(self, data):
        # A newline in HTML source is just whitespace; only block elements start a new rendered line.
        data = data.replace("\r", " ").replace("\n", " ")
        if self._ctx is not None and self._ctx_field:
            self._ctx_data(data)
        if self._unit is not None and self._measure_target:
            self._unit[self._measure_target].append(data.strip())
        for f in self.fact_stack:
            f["text"] += data
        if not self.hidden and not self.skip_text:
            self.buf.append(data)

    def close(self):
        super().close()
        self._new_page()

    # -- contexts and units (inside ix:resources) ---------------------------------------------------
    def _metadata_start(self, tag, a):
        if tag == "xbrli:context":
            self._ctx = Context(id=a.get("id", ""))
        elif self._ctx is not None:
            if tag in ("xbrli:startdate", "xbrli:enddate", "xbrli:instant"):
                self._ctx_field = tag.split(":")[1]
            elif tag in ("xbrldi:explicitmember", "xbrldi:typedmember"):
                self._member_dim = a.get("dimension", "")
                self._ctx_field = "member"
        if tag == "xbrli:unit":
            self._unit = {"id": a.get("id", ""), "num": [], "den": []}
            self._measure_target = None
        elif self._unit is not None:
            if tag == "xbrli:unitdenominator":
                self._unit["_in_den"] = True
            elif tag == "xbrli:measure":
                self._measure_target = "den" if self._unit.get("_in_den") else "num"

    def _ctx_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._ctx_field == "startdate":
            self._ctx.start = text
        elif self._ctx_field == "enddate":
            self._ctx.end = text
        elif self._ctx_field == "instant":
            self._ctx.instant = text
        elif self._ctx_field == "member" and self._member_dim:
            self._ctx.dims[self._member_dim] = self._ctx.dims.get(self._member_dim, "") + text

    def _metadata_end(self, tag):
        if tag in (
            "xbrli:startdate",
            "xbrli:enddate",
            "xbrli:instant",
            "xbrldi:explicitmember",
            "xbrldi:typedmember",
        ):
            self._ctx_field = None
        if tag == "xbrli:context" and self._ctx is not None:
            self.contexts[self._ctx.id] = self._ctx
            self._ctx = None
        if tag == "xbrli:measure":
            self._measure_target = None
        if tag == "xbrli:unit" and self._unit is not None:
            num = "*".join(m for m in self._unit["num"] if m)
            den = "*".join(m for m in self._unit["den"] if m)
            self.units[self._unit["id"]] = f"{num}/{den}" if den else num
            self._unit = None


# A rendered page longer than MAX_PAGE_CHARS (~3,000 tokens) is split at line boundaries into parts of
# at most SPLIT_PAGE_CHARS (~1,500 tokens). This covers documents with no page-break markup at all
# (position-based layouts) and oversized pages such as exhibit indexes. A single line longer than the
# limit stays whole.
MAX_PAGE_CHARS = 12_000
SPLIT_PAGE_CHARS = 6_000
_SPACES = re.compile(r"[ \t\r\f\v\xa0  ]+")  # incl. no-break and thin spaces
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")  # invisible; removed entirely


def _render_page(raw: str) -> tuple[list[str], dict[int, int]]:
    """Clean one page's lines; return them plus {fact index: number of the line that displays it}."""
    lines_out, where = [], {}
    for raw_line in raw.split("\n"):
        idxs = [int(m.group(1)) for m in _MARKER.finditer(raw_line) if m.group(1)]
        clean = _SPACES.sub(" ", _ZERO_WIDTH.sub("", _MARKER.sub("", raw_line))).strip()
        if not clean:
            continue
        for i in idxs:
            where[i] = len(lines_out)
        lines_out.append(clean)
    return lines_out, where


def _split_lines(lines: list[str]) -> list[list[str]]:
    """Keep a page whole if short enough; otherwise cut it into consecutive parts of <= SPLIT_PAGE_CHARS."""
    if sum(len(x) + 1 for x in lines) <= MAX_PAGE_CHARS:
        return [lines]
    parts, cur, size = [], [], 0
    for line in lines:
        if cur and size + len(line) + 1 > SPLIT_PAGE_CHARS:
            parts.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    return parts + [cur] if cur else parts


def _parse(html: str) -> _Reader:
    r = _Reader()
    r.feed(html)
    r.close()
    return r


def read_filing(html: str) -> Filing:
    """Parse one inline-XBRL HTML document into pages and located facts."""
    return _build(_parse(html), None, None)


def read_document_set(docs: dict[str, str]) -> dict[str, Filing]:
    """Parse a filing made of several inline-XBRL documents (e.g. a 10-K wrapper plus the annual report).

    Contexts and units declared in any document's header apply to facts in all of them (inline XBRL
    document sets), so they're merged before facts are built. Pages stay per document."""
    readers = {name: _parse(html) for name, html in docs.items()}
    contexts = {k: v for r in readers.values() for k, v in r.contexts.items()}
    units = {k: v for r in readers.values() for k, v in r.units.items()}
    return {name: _build(r, contexts, units) for name, r in readers.items()}


def _build(r: _Reader, contexts: dict[str, Context] | None, units: dict[str, str] | None) -> Filing:
    contexts = contexts if contexts is not None else r.contexts
    units = units if units is not None else r.units
    pages, located, split = [], {}, 0
    for raw in r.pages:
        lines, where = _render_page(raw)
        parts = _split_lines(lines)
        split += len(parts) > 1
        first_line = 0
        for part in parts:
            page_no = len(pages)
            pages.append("\n".join(part))
            for idx, line_no in where.items():
                if first_line <= line_no < first_line + len(part):
                    located.setdefault(idx, []).append(Occurrence(page_no, lines[line_no]))
            first_line += len(part)

    facts, skipped = [], {}
    for raw in sorted(r.raw_facts, key=lambda f: f["index"]):
        if raw["hidden"]:
            skipped["hidden"] = skipped.get("hidden", 0) + 1
            continue
        if raw.get("xsi:nil") == "true":
            skipped["nil"] = skipped.get("nil", 0) + 1
            continue
        number = parse_number(raw["text"], raw.get("format"))
        if number is None:
            skipped["unreadable_number"] = skipped.get("unreadable_number", 0) + 1
            continue
        if raw["index"] not in located:
            skipped["not_displayed"] = skipped.get("not_displayed", 0) + 1
            continue
        if raw.get("contextref", "") not in contexts:
            skipped["unknown_context"] = skipped.get("unknown_context", 0) + 1
            continue
        scale = int(raw.get("scale") or 0)
        value = number * (10**scale) * (-1 if raw.get("sign") == "-" else 1)
        facts.append(
            Fact(
                id=f"f{raw['index']}",
                concept=raw.get("name", ""),
                context=raw.get("contextref", ""),
                unit=units.get(raw.get("unitref", ""), raw.get("unitref") or None),
                value=value,
                display=re.sub(r"\s+", " ", raw["text"]).strip(),
                scale=scale,
                decimals=raw.get("decimals"),
                occurrences=located[raw["index"]],
            )
        )
    return Filing(
        pages=pages, facts=facts, contexts=contexts, units=units, skipped=skipped, split_pages=split
    )


def read_labels(xml_text: str) -> dict[str, dict[str, str]]:
    """Concept labels from a label linkbase (*_lab.xml): {concept qname: {role suffix: label}}.

    Role suffixes are the last part of the role URI: 'label' (standard), 'terseLabel', 'verboseLabel', ...
    Locator hrefs like 'https://.../us-gaap-2025.xsd#us-gaap_Revenues' become 'us-gaap:Revenues'.
    """
    ns = {"link": "http://www.xbrl.org/2003/linkbase", "xlink": "http://www.w3.org/1999/xlink"}
    X = "{http://www.w3.org/1999/xlink}"
    root = ET.fromstring(xml_text)
    out: dict[str, dict[str, str]] = {}
    for link in root.iter("{http://www.xbrl.org/2003/linkbase}labelLink"):
        locs = {}
        for loc in link.findall("link:loc", ns):
            frag = loc.get(f"{X}href", "").split("#")[-1]
            prefix, _, name = frag.partition("_")
            locs[loc.get(f"{X}label")] = f"{prefix}:{name}" if name else frag
        labels: dict[str, list[tuple[str, str]]] = {}
        for lab in link.findall("link:label", ns):
            role = lab.get(f"{X}role", "").rsplit("/", 1)[-1]
            labels.setdefault(lab.get(f"{X}label"), []).append((role, "".join(lab.itertext()).strip()))
        for arc in link.findall("link:labelArc", ns):
            concept = locs.get(arc.get(f"{X}from"))
            for role, text in labels.get(arc.get(f"{X}to"), []):
                if concept:
                    out.setdefault(concept, {})[role] = text
    return out
