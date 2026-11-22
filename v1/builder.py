"""Build the Filing-Evidence questions from the downloaded filings (PROTOCOL.md §3–§5).

Reads dataset/manifest.json and the filings in forge-data, and writes:
    dataset/questions.jsonl   one question per line: slice, wording, the pages shown (ids), gold answer
    dataset/pages.jsonl       the text of every page used, keyed by page id (shared by questions)
    dataset/stats.json        counts per slice / company / form / subtype, and candidate pool sizes

Everything is deterministic given SEED. Rules (each one is a function below, so it can be read and tested):
  - eligibility: displayed digits, a labelled line (>= 2 words), known unit, page <= MAX_TOKENS
  - slice assignment: one slice per fact, by page type, period, unit and dimensions
  - wording: the filer's own label, the company name, the period in words
  - ambiguity: dropped if the shown pages display a different value for the same item and period
  - S8 (not in the pages): checked against page text, not just tags (untagged tables exist)

    uv run python builder.py
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).parent
SEED = 20261115
PER_SLICE = 125
MAX_PER_COMPANY = 30
MIN_COMPANIES_PER_SLICE = 15
MAX_TOKENS = 3000  # per page, Qwen tokenizer (PROTOCOL §5)
UNITS = {
    "iso4217:USD": "USD",
    "iso4217:USD/xbrli:shares": "USD per share",
    "xbrli:shares": "shares",
    "xbrli:pure": "pure",
}
SLICES = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]

# A statement title, at the END of a short heading line (company names may precede it), in the styles
# seen across the 80 filings: "Consolidated Statements of Operations", "Statements of Consolidated Income",
# "Interim Condensed Consolidated Balance Sheets", "Consolidated Condensed Balance Sheets",
# "Income Statements", "Consolidated Financial Position", "Consolidated Statement of Cash Flow".
# Deliberately NOT matched: "Consolidated Results of Operations" (Caterpillar's statement title, but also a
# common MD&A section heading). Precision over recall: a missed statement page only loses candidates, while
# an MD&A page taken for a statement would put wrong questions in S1/S2.
_ADJ = r"((interim|unaudited|condensed|consolidated|combined)\s+)*"
STATEMENT_TITLE = re.compile(
    _ADJ + r"("
    r"statements?\s+of\s+(consolidated\s+)?(income|operations|earnings|comprehensive\s+(income|loss)"
    r"|financial\s+(condition|position)|cash\s+flows?|condition)"
    r"|balance\s+sheets?"
    r"|financial\s+position"
    r"|(income|cash\s+flows?|comprehensive\s+income)\s+statements?"
    r")(\s+and\s+comprehensive\s+(income|loss))?$",
    re.I,
)
# Trailing text removed from a heading before matching: periods ("at December 31", "for the years ended ...")
# and "Table of Contents" link text.
_HEADING_TAIL = re.compile(
    r"\s+((financial\s+)?table\s+of\s+contents|(for|at|as\s+of)\s+.*|"
    r"(years?|three|six|nine)\s+(months\s+)?ended\s+.*)$",
    re.I,
)
EQUITY_TITLE = re.compile(
    r"(stockholders|shareholders|share\s*owners|partners|members)['’]?\s+equity|"
    r"changes\s+in\s+(equity|capital)|equity\s+statements?",
    re.I,
)
NOTES_TITLE = re.compile(r"notes\s+to\s+(the\s+)?" + _ADJ + r"financial\s+statements", re.I)
# Headings that close the notes: the next Item after the financial statements, or the reports around them.
SECTION_END = re.compile(
    r"^\s*(item\s+(9a?|2|3)\b|report\s+of\s+independent|management['’]s\s+report\s+on\s+internal)", re.I
)
MIN_STATEMENT_FACTS = 5
LABEL_WORDS = re.compile(r"[A-Za-z]{2,}.*?[A-Za-z]{2,}")


# -- helpers that define the rules ------------------------------------------------------------------------


def head(page: str, n: int = 8) -> str:
    return "\n".join(page.split("\n")[:n])


def heading_lines(page: str, n: int = 6) -> list[str]:
    """Short lines near the top that can be titles: <= 10 words, not ending in a page number (tables of
    contents), not an index. Parentheticals ('(unaudited)', '(in millions)') and trailing periods or
    'Table of Contents' link text are removed."""
    out = []
    for line in page.split("\n")[:n]:
        t = re.sub(r"\([^)]*\)", " ", line)
        t = re.sub(r"[—–\-:,.]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if _toc_entry(t) or "index" in t.lower():
            continue
        t = _HEADING_TAIL.sub("", t).strip()
        if t and len(t.split()) <= 10:
            out.append(t)
    return out


_MONTHS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}


def _toc_entry(t: str) -> bool:
    """A table-of-contents line ends in a page number ("... 2026 32"), unlike a dated heading
    ("at December 31")."""
    m = re.search(r"(\S+)\s+(\d{1,3})$", t)
    return bool(m) and m.group(1).lower() not in _MONTHS


def is_statement_page(page: str, usd_facts_on_page: int = MIN_STATEMENT_FACTS) -> bool:
    """A primary financial statement (income, comprehensive income, balance sheet, cash flows); not
    equity, not a note. Needs a title line and real figures (rules out tables of contents and notes
    that mention a statement)."""
    heads = heading_lines(page)
    if any(NOTES_TITLE.search(t) or re.match(r"note\s+\d", t, re.I) for t in heads):
        return False
    titles = [t for t in heads if STATEMENT_TITLE.search(t)]
    return (
        bool(titles)
        and not any(EQUITY_TITLE.search(t) for t in titles)
        and usd_facts_on_page >= MIN_STATEMENT_FACTS
    )


def notes_range(pages: list[str], after: int) -> range:
    """Pages of the notes to the financial statements: the first notes title after the statements, up to the
    heading that closes the section (next Item, auditor's report, management's report on internal control).

    Titles seen: "Notes to the Interim Condensed Consolidated Financial Statements", "Notes to Consolidated
    Condensed Financial Statements", "NOTES TO UNAUDITED CONSOLIDATED FINANCIAL STATEMENTS", "Index to
    Combined Notes to Condensed Consolidated Financial Statements" (a combined filing's notes start there)."""

    def has_notes_title(page: str) -> bool:
        for line in page.split("\n")[:6]:
            t = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", line)).strip()
            if len(t.split()) <= 12 and not _toc_entry(t) and NOTES_TITLE.search(t):
                return True
        return False

    start = next((i for i in range(after + 1, len(pages)) if has_notes_title(pages[i])), None)
    if start is None:
        return range(0)
    end = next(
        (
            i
            for i in range(start + 1, len(pages))
            if any(SECTION_END.search(line) for line in pages[i].split("\n")[:4])
        ),
        len(pages),
    )
    return range(start, end)


def days(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def period_phrase(start: str | None, end: str | None, instant: str | None, form: str) -> str | None:
    """Period in words. None if the duration isn't a standard one (then the fact isn't used)."""

    def d(s: str) -> str:
        x = date.fromisoformat(s)
        return f"{x:%B} {x.day}, {x.year}"

    if instant:
        return f"as of {d(instant)}"
    n = days(start, end)
    if n is None:
        return None
    if 84 <= n <= 98:
        return f"for the three months ended {d(end)}"
    if 175 <= n <= 189:
        return f"for the six months ended {d(end)}"
    if 266 <= n <= 280:
        return f"for the nine months ended {d(end)}"
    if 357 <= n <= 371:
        return f"for the fiscal year ended {d(end)}"
    return None


def shift_years(iso: str, years: int) -> str | None:
    """Same calendar day `years` earlier (None if that day doesn't exist, e.g. Feb 29)."""
    try:
        return date.fromisoformat(iso).replace(year=date.fromisoformat(iso).year - years).isoformat()
    except ValueError:
        return None


def quarter_start(end_iso: str) -> str:
    """First day of the month two months before `end` (a three-month period ending on `end`)."""
    e = date.fromisoformat(end_iso)
    m = e.month - 2
    y = e.year - (1 if m <= 0 else 0)
    return date(y, m + 12 if m <= 0 else m, 1).isoformat()


def sentence_case(text: str) -> str:
    """Lowercase the first letter only for sentence-case labels ("Total revenues" -> "total revenues"), so the
    question reads naturally; title-case labels and names ("Sam's Club U.S.") stay as the filer wrote them."""
    words = text.split()
    long_words = [w for w in words if len(re.sub(r"[^A-Za-z]", "", w)) >= 4]
    if len(long_words) >= 2 and all(w.isupper() for w in long_words):
        # an all-capitals heading ("COMPREHENSIVE INCOME"): lower it, keeping short acronyms ("NEE", "U.S.");
        # a single capitalised word is an acronym ("EBITDA") and stays
        small = {"to", "of", "and", "net", "for", "in", "on", "the", "or", "by", "per", "at"}
        return " ".join(
            w.lower() if len(re.sub(r"[^A-Za-z]", "", w)) >= 4 or w.lower() in small else w for w in words
        )
    later_caps = sum(w[0].isupper() for w in words[1:] if w[:1].isalpha())
    if words and words[0][:1].isupper() and words[0][1:2].islower() and later_caps == 0:
        return text[0].lower() + text[1:]
    return text


def label_of(labels: dict, concept: str) -> str | None:
    """The filer's XBRL label (terse, else standard), without a trailing [Member]/[Axis] tag."""
    roles = labels.get(concept, {})
    text = roles.get("terseLabel") or roles.get("label")
    if not text:
        return None
    text = re.sub(r"\s*\[(member|axis|domain|line items|table|abstract)\]\s*$", "", text, flags=re.I).strip()
    text = clean_label(text)
    return sentence_case(text) if text else None


def plain_label(labels: dict, concept: str) -> str | None:
    """An XBRL label usable in a question: rejects the inverted taxonomy style ("Premiums Written, Net",
    "Goodwill, Impaired, Accumulated Impairment Loss"), which doesn't read as a line item."""
    text = label_of(labels, concept)
    return text if text and "," not in text else None


# -- question wording (redesigned after hand-check round 2; see qc/handcheck_v1.jsonl, v2.jsonl) ----------
#
# Principle: a question is kept only if a careful reader of the shown pages would point to the same row.
# The item is named by its printed row label (unique on the shown pages); a short label gets its section
# heading only when that heading is reliably found; anything doubtful is dropped (pools are large).

# Where a row's figures start: a number, "$", "(" before a number, or a dash used as an empty cell (a dash
# followed by another figure or the end of the line, not by words: "awards — allocated income" is a label).
_FIRST_FIGURE = re.compile(r"(?:^|\s)(?:[$(]?\s?\d|[—–](?=\s*(?:$|[$(]?\s?[\d—–])))")
# A parenthetical holding both words and figures is commentary, not part of the row's name.
_WORDY_PAREN = re.compile(r"\((?=[^()]*[A-Za-z]{2,})(?=[^()]*\d)[^()]*\)")
_UNIT_SUFFIX = re.compile(
    r"\s*\((in\s+)?(shares|dollars(\s+per\s+share)?|millions|thousands|billions|percent|usd|\$)\)", re.I
)
_CUT_END = re.compile(r"\b(of|at|and|or|to|for|in|on|by|from|with|net|less)[\s,]*$|,\s*$", re.I)
_STOP = {"the", "and", "for", "from", "with", "that", "this", "total", "other", "net", "less", "plus", "per"}
_MONTH_WORD = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?$",
    re.I,
)
_SENTENCE_START = re.compile(r"^(the|a|an|this|these|our|we)\b|.*\bregistrant", re.I)
_ROLL_FORWARD = re.compile(r"^(net\s+)?(balance|beginning|ending|balances)\b", re.I)
# Summary rows close a block: never given context, and the upward search for a heading stops at them.
_SUMMARY = re.compile(
    r"^(total|net\s+(income|loss|earnings|\(loss\)|cash|increase|decrease|change|revenues?|sales|investment)|"
    r"consolidated|operating\s+(income|profit|loss)|(income|earnings|loss)(\s+\(loss\))?\s+before|"
    r"gross\s+(profit|margin)|comprehensive\s+income)",
    re.I,
)
# Lines that look like headings but are captions or column headers.
_NOT_HEADING = re.compile(
    r"millions|thousands|billions|except per share|fiscal year|years? ended|months ended|"
    r"quarters? ended|unaudited|\$ in|^\(|^as of\b|^at\b|"
    r"\btotal\b|\b(numerator|denominator)\b",  # column headers ("Segment Total All Other Total"), EPS parts
    re.I,
)
# Totals that name what they total ("Total assets", "Total revenues") stand on their own; "Total deferred"
# doesn't.
_SELF_TOTALS = {
    "assets",
    "liabilities",
    "revenues",
    "revenue",
    "equity",
    "expenses",
    "costs",
    "debt",
    "deposits",
    "loans",
    "investments",
    "sales",
    "capitalization",
    "borrowings",
    "income",
    "receivables",
    "inventories",
    "goodwill",
    "securities",
    "premiums",
    "dividends",
    "leases",
}


def figure_start(line: str) -> int | None:
    m = _FIRST_FIGURE.search(_WORDY_PAREN.sub(lambda p: " " * len(p.group(0)), line))
    return m.start() if m else None


def clean_label(text: str) -> str:
    """Remove unit suffixes ("(in shares)"), glued footnote markers ("stock1", "(loss)1", "costs*"), and
    leading or trailing dashes and punctuation."""
    text = _UNIT_SUFFIX.sub("", text)
    text = re.sub(r"(?<=[a-z)])\d{1,2}$", "", text.strip())
    return text.strip(" *:,-–—").strip()


def row_label(line: str) -> str | None:
    """The row's label as printed: the text before the first figure, without footnote markers like (1) or
    figure-bearing parentheticals like "(Note 6)". None when it can't name a row on its own: fewer than two
    words, longer than 16, cut mid-phrase, ends in a month ("as of May"), or a roll-forward balance row."""
    line = _WORDY_PAREN.sub(" ", line)
    i = figure_start(line)
    head = line[:i] if i is not None else line
    head = re.sub(r"\(\s*(\d{1,2}|[a-z])\s*\)", " ", head)
    head = clean_label(re.sub(r"\s+", " ", head))
    head = re.sub(r"^(numerator|denominator)\s*[–—:-]\s*", "", head, flags=re.I)  # "Numerator – net income"
    words = head.split()
    if sum(bool(re.search(r"[A-Za-z]{2,}", w)) for w in words) < 2 or len(words) > 16:
        return None
    if "$" in head or _CUT_END.search(head) or head.count("(") != head.count(")"):
        return None
    if _MONTH_WORD.search(head) or _ROLL_FORWARD.search(head):
        return None
    if _SENTENCE_START.match(head):
        return None  # a sentence fragment ("The number of the registrant's Common Shares"), not a row name
    return head


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


def label_matches_line(label: str, line: str) -> bool:
    """Most of a label's content words appear in the evidence text, so the question points at what the
    reader sees (rules out vague or mismatched XBRL labels such as "liability balance")."""
    words = content_words(label)
    return bool(words) and len(words & content_words(line)) / len(words) >= 0.6


def sentence_with(text: str, display: str) -> str:
    """The sentence of a prose line that contains the figure."""
    for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])", text):
        if display in s:
            return s
    return text


def embedded_in_text(line: str, display: str) -> bool:
    """The figure sits inside the row's wording (e.g. "...net of tax of $1 and $3 ..."), not in a column:
    a word follows its first appearance on the line (column figures are followed only by figures)."""
    i = line.find(display)
    return i >= 0 and bool(re.search(r"[A-Za-z]{2,}", line[i + len(display) :]))


def unique_row(doc: Doc, label: str, fact, pages: list[int]) -> bool:
    """The row label points to one row on the shown pages: every shown line with this label is the
    answer's own row or displays the same figure (the same row repeated)."""
    want = label.lower()
    for p in pages:
        for line in doc.pages[p].split("\n"):
            rl = row_label(line)
            if rl and rl.lower() == want and fact.display not in line:
                return False
    return True


def is_summary(label: str) -> bool:
    return bool(_SUMMARY.match(label))


def reliable_heading(page: str, line: str, max_rows: int = 6) -> str | None:
    """The heading of the block a row belongs to: the nearest line above with no figures, at most
    `max_rows` rows up, with no summary row in between, and not a caption or column header."""
    lines = page.split("\n")
    if line not in lines:
        return None
    i = lines.index(line)
    rows = 0
    for j in range(i - 1, -1, -1):
        t = lines[j].strip()
        if re.search(r"\d", t):
            rl = row_label(t)
            if rl and is_summary(rl):
                return None  # a summary row closes the block above it
            rows += 1
            if rows > max_rows:
                return None
            continue
        if (
            len(t.split()) > 8
            or t.endswith(".")
            or _NOT_HEADING.search(t)
            or not re.search(r"[A-Za-z]{3,}", t)
        ):
            return None
        return clean_label(re.sub(r"\s*\(\s*(\d{1,2}|[a-z])\s*\)", "", t)) or None
    return None


def stands_alone(label: str, on_statement: bool, company: str) -> bool:
    """Whether a row label names its item without help. Primary-statement rows of two or more words do
    (statements use conventional line items); elsewhere three or more words are needed. A label that is just
    the company's (or a registrant's) name never does."""
    words = content_words(label)
    if not words or words <= content_words(company):
        return False
    if re.match(r"\s*(%|percent)", label, re.I):
        return False  # a percentage of what? needs its heading
    n = len(re.findall(r"[A-Za-z]{2,}", label))
    return n >= (2 if on_statement else 3)


# One-word labels that name a standard line item ("Goodwill", "Revenues"). Change words that need their
# table's subject ("Acquisitions", "Write-offs", "Adjustments") are deliberately not here.
_LINE_ITEM_NOUNS = {
    "goodwill",
    "revenues",
    "revenue",
    "assets",
    "liabilities",
    "inventories",
    "depreciation",
    "amortization",
    "sales",
    "receivables",
    "deposits",
    "loans",
    "equity",
    "backlog",
}
_GENERIC_FIRST = {"other", "less", "add", "net", "adjustments", "adjustment", "changes", "change"}


def specific_label(label: str) -> bool:
    """An XBRL label specific enough to name an item without a row: a standard line-item noun ("Goodwill"),
    or two or more words (a hyphenated word counts once) that aren't a short generic phrase ("Other
    Adjustments"); a total only if it says what it totals ("Total Assets"). Change words ("Acquisitions",
    "Write-offs") never qualify alone."""
    words = [w for w in label.split() if re.search(r"[A-Za-z]{2,}", w)]
    if len(words) == 1:
        return re.sub(r"[^a-z]", "", words[0].lower()) in _LINE_ITEM_NOUNS
    if not words:
        return False
    first = re.sub(r"[^a-z]", "", words[0].lower())
    if first == "total":
        return self_explanatory_total(label)
    return not (len(words) <= 2 and first in _GENERIC_FIRST)


def self_explanatory_total(label: str) -> bool:
    words = re.findall(r"[A-Za-z]+", label.lower())
    if not words or words[0] != "total":
        return True
    return len(words) >= 3 or (len(words) == 2 and words[1] in _SELF_TOTALS)


def row_item_label(doc: Doc, fact, pages: list[int]) -> str | None:
    """How a table-row question names its item, or None to drop the question (see the principle above)."""
    occ = fact.occurrences[0]
    rl = row_label(occ.line)
    if not rl or not unique_row(doc, rl, fact, pages):
        return None  # no usable or no unique label: never fall back to an XBRL label for a row
    label = sentence_case(rl)
    if is_summary(rl):
        return label if self_explanatory_total(rl) else None
    heading = reliable_heading(doc.pages[occ.page], occ.line)
    useful = (
        heading
        and not content_words(heading) <= content_words(rl)
        and not content_words(rl) <= content_words(heading)
    )
    if stands_alone(rl, occ.page in doc.statement_pages, doc.company):
        short = len(re.findall(r"[A-Za-z]{2,}", rl)) <= 3
        return f"{label} ({sentence_case(heading)})" if useful and short else label
    return f"{label} ({sentence_case(heading)})" if useful else None


def item_label(doc: Doc, fact, pages: list[int]) -> str | None:
    """Table rows: the printed row label (row_item_label). Prose: the filer's XBRL label, which must match
    the sentence that contains the figure."""
    line = fact.occurrences[0].line
    if prose_words(line) < 20:
        return row_item_label(doc, fact, pages)
    label = plain_label(doc.labels, fact.concept)
    if not label or len(re.findall(r"[A-Za-z]{2,}", label)) < 2:
        return None
    sentence = sentence_with(line, fact.display)
    if not label_matches_line(label, sentence) or qualified_in_sentence(label, sentence):
        return None
    return label


# After the item's name, a qualifier that narrows it ("depreciation and amortization expense for property,
# plant and equipment"), as opposed to the period ("... for the three months ended").
_QUALIFIER = re.compile(
    r"^\s*(expenses?|costs?|charges?)?\s*(for|of|on|related to|attributable to|associated with|from)\s+"
    r"(?!(the\s+)?(three|six|nine|twelve|fiscal|years?|quarters?|periods?|months|20\d\d)\b)",
    re.I,
)


def qualified_in_sentence(label: str, sentence: str) -> bool:
    """The sentence names a narrower item than the label: the label appears verbatim and is followed by a
    qualifier, so a question using the label alone would read as the broader figure."""
    i = sentence.lower().find(label.lower())
    return i >= 0 and bool(_QUALIFIER.match(sentence[i + len(label) :]))


def displayed_number(display: str) -> float | None:
    t = display.replace(",", "").replace("$", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def tokens(text: str, tok) -> int:
    return len(tok(text, add_special_tokens=False)["input_ids"])


# -- data model -------------------------------------------------------------------------------------------


@dataclass
class Doc:
    ticker: str
    company: str
    form: str
    accession: str
    report_date: str
    name: str
    pages: list[str]
    facts: list
    contexts: dict
    labels: dict
    statement_pages: set = field(default_factory=set)
    notes_pages: set = field(default_factory=set)
    page_tokens: list[int] = field(default_factory=list)
    by_concept: dict = field(default_factory=dict)  # concept -> facts (built once; avoids O(n^2) scans)
    by_line: dict = field(default_factory=dict)  # (page, line) -> facts displayed on that line

    def index(self) -> None:
        self.by_concept = defaultdict(list)
        self.by_line = defaultdict(list)
        for f in self.facts:
            self.by_concept[f.concept].append(f)
            for o in f.occurrences:
                self.by_line[(o.page, o.line)].append(f)

    def page_id(self, i: int) -> str:
        return f"{self.accession}/{self.name}#p{i}"


def load_docs(tok) -> list[Doc]:
    from ixbrl import read_document_set, read_labels
    from paths import data_dir

    manifest = json.loads((HERE / "dataset" / "manifest.json").read_text())
    names = yaml.safe_load((HERE / "companies.yaml").read_text())["names"]
    root = data_dir() / "finance" / "filings"
    docs = []
    for f in manifest["filings"]:
        folder = root / f["ticker"] / f["accession"]
        texts = {
            d["name"]: (folder / d["name"]).read_text(encoding="utf-8", errors="replace")
            for d in f["files"]["documents"]
        }
        labels = read_labels(
            (folder / f["files"]["labels"]["name"]).read_text(encoding="utf-8", errors="replace")
        )
        for name, parsed in read_document_set(texts).items():
            doc = Doc(
                f["ticker"],
                names[f["ticker"]],
                f["form"],
                f["accession"],
                f["report_date"],
                name,
                parsed.pages,
                parsed.facts,
                parsed.contexts,
                labels,
            )
            usd_per_page = Counter(
                f.occurrences[0].page
                for f in doc.facts
                if f.unit == "iso4217:USD" and not doc.contexts[f.context].dims
            )
            doc.statement_pages = {
                i for i, p in enumerate(doc.pages) if is_statement_page(p, usd_per_page[i])
            }
            doc.notes_pages = set(notes_range(doc.pages, min(doc.statement_pages, default=-1)))
            doc.page_tokens = [tokens(p, tok) for p in doc.pages]
            doc.index()
            docs.append(doc)
    return docs


# -- candidates per slice ---------------------------------------------------------------------------------


def eligible(doc: Doc, fact) -> bool:
    occ = fact.occurrences[0]
    table_row = prose_words(occ.line) < 20
    return (
        bool(re.search(r"\d", fact.display))
        and displayed_number(fact.display) is not None
        and fact.unit in UNITS
        and bool(LABEL_WORDS.search(occ.line))
        and doc.page_tokens[occ.page] <= MAX_TOKENS
        and not (table_row and embedded_in_text(occ.line, fact.display))
        and not split_by_category(doc, fact)
        and not multi_measure_row(doc, fact)
        and not (table_row and sparse_row(doc.pages[occ.page], occ.line))
    )


def multi_measure_row(doc: Doc, fact) -> bool:
    """The row shows other items for the same period (e.g. a stock-option row with count, price, term and
    intrinsic value): the question can't say which figure it means."""
    ctx = doc.contexts[fact.context]
    if ctx.dims:
        return False
    occ = fact.occurrences[0]
    for x in doc.by_line.get((occ.page, occ.line), []):
        c = doc.contexts[x.context]
        if (
            x.concept != fact.concept
            and not c.dims
            and (c.start, c.end, c.instant) == (ctx.start, ctx.end, ctx.instant)
        ):
            return True
    return False


_FIGURE = re.compile(r"(?<![\w.])\(?-?\$?\s?\d[\d,]*(\.\d+)?\)?%?(?![\w])|(?<![\w])[—–](?![\w])")


def trailing_figures(line: str) -> int | None:
    """How many figures follow the row's label (None if the line doesn't start with a label)."""
    line = _WORDY_PAREN.sub(" ", line)
    m = _FIRST_FIGURE.search(line)
    if not m or not re.search(r"[A-Za-z]{2,}", line[: m.start()]):
        return None
    return len(_FIGURE.findall(line[m.start() :]))


def prose_words(line: str) -> int:
    """Words in a line, not counting figures or currency signs (a table row has few, a sentence many)."""
    return len(re.findall(r"[A-Za-z]{2,}", line))


def table_block(lines: list[str], i: int, limit: int = 40) -> list[str]:
    """The table a row belongs to: the unbroken run of figure-bearing rows around line i (ends at a heading,
    a sentence, or a line without figures)."""

    def in_table(x: str) -> bool:
        return prose_words(x) < 20 and trailing_figures(x) is not None

    lo = i
    while lo - 1 >= max(0, i - limit) and in_table(lines[lo - 1]):
        lo -= 1
    hi = i
    while hi + 1 < min(len(lines), i + limit + 1) and in_table(lines[hi + 1]):
        hi += 1
    return lines[lo : hi + 1]


def sparse_row(page: str, line: str) -> bool:
    """The row has fewer figures than the widest row of its own table: some columns are blank, and in
    plain text a reader can't tell which column each figure is in (e.g. Schedule III segment rows).
    Only rows of the same table are compared, so a narrower table stacked next to a wider one is fine."""
    lines = page.split("\n")
    if line not in lines:
        return False
    i = lines.index(line)
    mine = trailing_figures(line)
    if mine is None:
        return False
    widest = max((trailing_figures(x) or 0 for x in table_block(lines, i)), default=mine)
    return mine < widest


def split_by_category(doc: Doc, fact) -> bool:
    """A total-company figure whose row also shows same-period figures broken down by a dimension (category
    columns): the question can't name the column, so it's ambiguous."""
    ctx = doc.contexts[fact.context]
    if ctx.dims:
        return False
    occ = fact.occurrences[0]
    for x in doc.by_line.get((occ.page, occ.line), []):
        c = doc.contexts[x.context]
        if x is not fact and c.dims and (c.start, c.end, c.instant) == (ctx.start, ctx.end, ctx.instant):
            return True
    return False


_OPERATING_SEGMENTS = ("us-gaap:ConsolidationItemsAxis", "us-gaap:OperatingSegmentsMember")


def segment_member(dims: dict) -> str | None:
    """The segment a fact belongs to, if its only dimension is a segment (axis ending in SegmentsAxis).
    A ConsolidationItemsAxis = OperatingSegmentsMember tag alongside it (common since ASU 2023-07) only marks
    the figure as an operating-segment amount, so it's allowed; any other extra dimension is not."""
    rest = {a: m for a, m in dims.items() if (a, m) != _OPERATING_SEGMENTS}
    if len(rest) == 1:
        axis, member = next(iter(rest.items()))
        if axis.endswith("SegmentsAxis"):
            return member
    return None


def slice_of(doc: Doc, fact) -> str | None:
    """Assign one slice (S1–S7) or None.

    Order matters: units first, then segments, prose, statements, notes."""
    ctx = doc.contexts[fact.context]
    occ = fact.occurrences[0]
    dims = ctx.dims
    words = prose_words(occ.line)  # real words: figures and $ signs don't make a row prose
    on_statement = occ.page in doc.statement_pages
    current = ctx.period_end == doc.report_date
    if dims:
        if segment_member(dims) and words < 20 and UNITS[fact.unit] == "USD":
            return "S5"
        return None
    if UNITS[fact.unit] != "USD":
        return "S7" if words < 20 else None
    if words >= 20 and not on_statement:
        return "S6"
    if on_statement:
        n = days(ctx.start, ctx.end)
        if doc.form == "10-Q" and n is not None:
            return "S3" if current else "S2"
        return "S1" if current else "S2"
    if occ.page in doc.notes_pages:
        return "S4"
    return None


def quarter_ytd_pair(doc: Doc, fact) -> bool:
    """S3 needs the page to show both a three-month and a longer year-to-date figure for this item."""
    ctx = doc.contexts[fact.context]
    n = days(ctx.start, ctx.end)
    same = [
        x
        for x in doc.by_concept[fact.concept]
        if not doc.contexts[x.context].dims
        and x.occurrences[0].page == fact.occurrences[0].page
        and doc.contexts[x.context].end == ctx.end
    ]
    lengths = {days(doc.contexts[x.context].start, doc.contexts[x.context].end) for x in same}
    return n is not None and any(84 <= m <= 98 for m in lengths if m) and any(m and m > 150 for m in lengths)


def question_text(doc: Doc, fact, pages: list[int]) -> tuple[str, str] | None:
    """(question, the item label used). Segment questions name the item by its XBRL label plus the segment,
    because a segment table's row label is usually just the segment's name."""
    ctx = doc.contexts[fact.context]
    period = period_phrase(ctx.start, ctx.end, ctx.instant, doc.form)
    if not period:
        return None
    if ctx.dims:
        member = plain_label(doc.labels, segment_member(ctx.dims) or "")
        label = segment_item_label(doc, fact, pages, member)
        if not label or not member:
            return None
        seg = member if member.lower().endswith("segment") else f"{member} segment"
        return f"What was {doc.company}'s {label} for its {seg} {period}?", label
    label = item_label(doc, fact, pages)
    if not label:
        return None
    return f"What was {doc.company}'s {label}{unit_hint(fact.unit, label)} {period}?", label


def segment_item_label(doc: Doc, fact, pages: list[int], member: str | None) -> str | None:
    """A segment question names the item by the row label when the row is the item (e.g. "Unaffiliated
    revenues", with segments as columns); when the row is the segment's name (segments as rows), by the
    XBRL label, which must then appear in the row or the lines above it (the table's title or headings)."""
    if not member:
        return None
    occ = fact.occurrences[0]
    rl = row_label(occ.line)
    if rl and len(content_words(rl) & content_words(member)) < 0.5 * max(1, len(content_words(rl))):
        return row_item_label(doc, fact, pages)  # segments as columns: the row is the item
    label = plain_label(doc.labels, fact.concept)
    lines = doc.pages[occ.page].split("\n")
    i = lines.index(occ.line) if occ.line in lines else 0
    context = " ".join(lines[max(0, i - 15) : i + 1])
    return label if label and specific_label(label) and label_matches_line(label, context) else None


def unit_hint(unit: str, label: str) -> str:
    """Say the unit when it isn't dollars, so a row that shows several kinds of figures isn't ambiguous."""
    kind = UNITS[unit]
    low = label.lower()
    if kind == "shares" and "share" not in low:
        return " (number of shares)"
    if kind == "shares":
        return " (number)"
    if kind == "USD per share" and "per share" not in low:
        return " (per share)"
    if kind == "pure" and "%" not in low and "percent" not in low and "rate" not in low:
        return " (%)"
    return ""


def shown_pages(doc: Doc, gold_page: int, rnd: random.Random) -> list[int] | None:
    """Gold page, an adjacent page, a random distractor; all within the token limit; order shuffled."""
    ok = [i for i, t in enumerate(doc.page_tokens) if t <= MAX_TOKENS and doc.pages[i].strip()]
    adj = [i for i in (gold_page - 1, gold_page + 1) if i in ok]
    others = [i for i in ok if abs(i - gold_page) > 1]
    if not adj or not others:
        return None
    pages = [gold_page, rnd.choice(adj), rnd.choice(others)]
    rnd.shuffle(pages)
    return pages


def period_shown(doc: Doc, fact) -> bool:
    """The answer page shows the period end's month and day (and year), so a reader can match the question's
    period to a column. Years alone aren't enough: retailers head columns "2025 2024 2023" by fiscal year
    *start*, so the year ending January 28, 2024 is the "2023" column."""
    ctx = doc.contexts[fact.context]
    end = ctx.end or ctx.instant
    if not end:
        return False
    d = date.fromisoformat(end)
    page = doc.pages[fact.occurrences[0].page]
    month = rf"({d:%B}|{d:%b}\.?{'|Sept' if d.month == 9 else ''})"
    return bool(re.search(rf"\b{month}\s+{d.day}\b", page, re.I)) and str(d.year) in page


def ambiguous(doc: Doc, fact, pages: list[int]) -> bool:
    """Another fact with the same item, period and dimensions but a different value on the shown pages."""
    ctx = doc.contexts[fact.context]
    for x in doc.by_concept[fact.concept]:
        if x is fact:
            continue
        c = doc.contexts[x.context]
        if (
            (c.start, c.end, c.instant, c.dims) == (ctx.start, ctx.end, ctx.instant, ctx.dims)
            and x.value != fact.value
            and any(o.page in pages for o in x.occurrences)
        ):
            return True
    return False


def gold(doc: Doc, fact, pages: list[int], label: str) -> dict:
    ctx = doc.contexts[fact.context]
    shown = displayed_number(fact.display)
    return {
        "status": "found",
        "concept": fact.concept,
        "label": label,
        "display": fact.display,
        "shown_value": shown,
        "negative": fact.value < 0,
        "scale": fact.scale,
        "unit": UNITS[fact.unit],
        "value": fact.value,
        "period": {"start": ctx.start, "end": ctx.end, "instant": ctx.instant},
        "dims": ctx.dims,
        "fact_id": fact.id,
        "evidence": [
            {"page": doc.page_id(o.page), "line": o.line} for o in fact.occurrences if o.page in pages
        ],
    }


# -- S8: not in the provided pages ------------------------------------------------------------------------


def s8_candidates(docs: list[Doc], rnd: random.Random) -> list[dict]:
    """Four kinds (PROTOCOL §4): (a) period not shown, (b) item not reported, (c) quarter of a 10-K,
    (d) item elsewhere in the filing but not on the shown pages. Each is verified against page *text*."""
    out = []
    # concepts reported by >= 5 companies, with a plain label of <= 8 words (for kind b)
    companies_per_concept: dict = defaultdict(set)
    for d in docs:
        for f in d.facts:
            companies_per_concept[f.concept].add(d.ticker)
    popular = sorted(c for c, t in companies_per_concept.items() if len(t) >= 5 and c.startswith("us-gaap:"))
    # point-in-time concepts (balances), so a "not reported" item is asked with the right kind of period
    instant_concepts = {f.concept for d in docs for f in d.facts if d.contexts[f.context].instant}
    for doc in docs:
        tagged = {f.concept for f in doc.facts}
        usable = [
            f
            for f in doc.facts
            if eligible(doc, f) and not doc.contexts[f.context].dims and UNITS[f.unit] == "USD"
        ]
        stmt = [f for f in usable if f.occurrences[0].page in doc.statement_pages]
        # (a) a year before anything shown on the page, asked of the statement's own pages
        for f in rnd.sample(stmt, min(4, len(stmt))):
            ctx = doc.contexts[f.context]
            end = ctx.end or ctx.instant
            years = {int(y) for y in re.findall(r"\b(20\d\d)\b", doc.pages[f.occurrences[0].page])}
            if not years or not end:
                continue
            old = min(years) - 1
            shift = int(end[:4]) - old
            old_end = shift_years(end, shift)
            old_start = shift_years(ctx.start, shift) if ctx.start else None
            pages = shown_pages(doc, f.occurrences[0].page, rnd)
            if (
                old_end
                and (old_start or not ctx.start)
                and pages
                and not any(str(old) in doc.pages[p] for p in pages)
            ):
                out.append(
                    _s8(
                        doc,
                        "a",
                        f.concept,
                        old_start,
                        None if ctx.instant else old_end,
                        old_end if ctx.instant else None,
                        pages,
                        item_label(doc, f, pages),
                    )
                )
        # (b) an item this company doesn't report: a concept common in other filings, absent here
        common = [c for c in popular if c not in tagged]
        for c in rnd.sample(common, min(8, len(common))):
            lab = next((plain_label(d.labels, c) for d in docs if plain_label(d.labels, c)), None)
            if not stmt or not lab or not 2 <= len(lab.split()) <= 8:
                continue
            same_type = [x for x in stmt if bool(doc.contexts[x.context].instant) == (c in instant_concepts)]
            if not same_type:
                continue
            f = rnd.choice(same_type)
            ctx = doc.contexts[f.context]
            pages = shown_pages(doc, f.occurrences[0].page, rnd)
            shown_words = set().union(*(content_words(doc.pages[p]) for p in pages)) if pages else set()
            if pages and len(re.findall(r"[A-Za-z]{2,}", lab)) >= 2 and not content_words(lab) & shown_words:
                out.append(_s8(doc, "b", c, ctx.start, ctx.end, ctx.instant, pages, lab))
        # (c) a three-month figure asked of a 10-K's income statement (10-Ks report the year)
        if doc.form == "10-K":
            flows = [
                f
                for f in stmt
                if doc.contexts[f.context].start
                and days(doc.contexts[f.context].start, doc.contexts[f.context].end) > 300
                and doc.contexts[f.context].end == doc.report_date
            ]
            for f in rnd.sample(flows, min(2, len(flows))):
                end = doc.contexts[f.context].end
                q_start = quarter_start(end)
                pages = shown_pages(doc, f.occurrences[0].page, rnd)
                has_quarter = any(
                    84 <= (days(doc.contexts[x.context].start, doc.contexts[x.context].end) or 0) <= 98
                    for x in doc.by_concept[f.concept]
                )
                if (
                    pages
                    and not has_quarter
                    and not any(
                        re.search(r"three months|fourth quarter|quarter ended", doc.pages[p], re.I)
                        for p in pages
                    )
                ):
                    out.append(_s8(doc, "c", f.concept, q_start, end, None, pages, item_label(doc, f, pages)))
        # (d) an item displayed elsewhere in the filing, with three pages that don't show it
        for f in rnd.sample(usable, min(4, len(usable))):
            ctx = doc.contexts[f.context]
            far = [
                i
                for i, t in enumerate(doc.page_tokens)
                if t <= MAX_TOKENS and all(abs(i - o.page) > 2 for o in f.occurrences)
            ]
            if len(far) < 4:
                continue
            g = rnd.choice(far)
            pages = shown_pages(doc, g, rnd)
            lab = item_label(doc, f, [f.occurrences[0].page])
            if (
                pages
                and lab
                and all(o.page not in pages for o in f.occurrences)
                and not any(f.display in doc.pages[p] or lab.lower() in doc.pages[p].lower() for p in pages)
            ):
                out.append(_s8(doc, "d", f.concept, ctx.start, ctx.end, ctx.instant, pages, lab))
    return [q for q in out if q is not None]


def _s8(doc, kind, concept, start, end, instant, pages, label):
    period = period_phrase(start, end, instant, doc.form)
    if not label or not period:
        return None
    return {
        "slice": "S8",
        "subtype": kind,
        "doc": doc,
        "pages": pages,
        "question": f"What was {doc.company}'s {label} {period}?",
        "gold": {
            "status": "not_found",
            "concept": concept,
            "label": label,
            "period": {"start": start, "end": end, "instant": instant},
        },
        "key": f"S8{kind}:{doc.accession}:{concept}:{start}:{end}:{instant}",
    }


# -- sampling ---------------------------------------------------------------------------------------------


def candidates(docs: list[Doc], rnd: random.Random) -> dict[str, list[dict]]:
    pool: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        for fact in doc.facts:
            if not eligible(doc, fact):
                continue
            s = slice_of(doc, fact)
            if s is None or (s == "S3" and not quarter_ytd_pair(doc, fact)):
                continue
            pages = shown_pages(doc, fact.occurrences[0].page, rnd)
            if pages is None or ambiguous(doc, fact, pages):
                continue
            worded = question_text(doc, fact, pages)
            if worded is None or not period_shown(doc, fact):
                continue
            q, label = worded
            ctx = doc.contexts[fact.context]
            pool[s].append(
                {
                    "slice": s,
                    "subtype": None,
                    "doc": doc,
                    "pages": pages,
                    "question": q,
                    "gold": gold(doc, fact, pages, label),
                    "key": f"{doc.accession}:{fact.concept}:{ctx.start}:{ctx.end}:{ctx.instant}:"
                    f"{sorted(ctx.dims.items())}",
                }
            )
    pool["S8"] = s8_candidates(docs, rnd)
    return pool


def sample_slice(
    s: str, cands: list[dict], per_company: Counter, used_keys: set, rnd: random.Random
) -> tuple[list[dict], Counter, Counter]:
    """Pick up to PER_SLICE questions for one slice (rules in `sample`)."""
    queues: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for c in cands:
        queues[c["doc"].ticker][c["doc"].form].append(c)
    for forms in queues.values():
        for lst in forms.values():
            rnd.shuffle(lst)
    companies = sorted(queues)
    rnd.shuffle(companies)
    got: list[dict] = []
    form_count: Counter = Counter()
    sub_count: Counter = Counter()
    sub_target = {k: PER_SLICE // 4 + (1 if i < PER_SLICE % 4 else 0) for i, k in enumerate("abcd")}
    seen_items: set = set()

    def take(t: str, form: str) -> bool:
        lst = queues[t][form]
        while lst:
            c = lst.pop()
            # one question per item per company; in S5 each segment's figure is its own item
            item = (t, c["gold"]["concept"], c["subtype"], str(sorted((c["gold"].get("dims") or {}).items())))
            if c["key"] in used_keys or item in seen_items or c["question"] in used_keys:
                continue
            if s == "S8" and sub_count[c["subtype"]] >= sub_target[c["subtype"]]:
                continue
            got.append(c)
            used_keys.add(c["key"])
            used_keys.add(c["question"])  # question text unique across the dataset
            seen_items.add(item)
            per_company[t] += 1
            form_count[form] += 1
            sub_count[c["subtype"]] += 1
            return True
        return False

    progress = True
    while len(got) < PER_SLICE and progress:
        progress = False
        for t in companies:
            if len(got) >= PER_SLICE or per_company[t] >= MAX_PER_COMPANY:
                continue
            order = sorted(("10-K", "10-Q"), key=lambda f: (form_count[f], f))  # the scarcer form first
            if take(t, order[0]) or take(t, order[1]):
                progress = True
    return got, form_count, sub_count


def sample(pool: dict[str, list[dict]], rnd: random.Random) -> tuple[list[dict], dict]:
    """Pick PER_SLICE questions per slice, balanced and spread out:
    - slices are filled scarcest first, so rare slices get first pick of each company's quota;
    - companies take turns (fixed random order), at most MAX_PER_COMPANY questions per company overall;
    - each pick takes the form (10-K / 10-Q) this slice has fewer of so far, if the company has one;
    - one question per item (concept) per company per slice; S8 split evenly across its four kinds."""
    per_company: Counter = Counter()
    used_keys: set = set()
    chosen, report = [], {}
    for s in sorted(SLICES, key=lambda s: len(pool[s])):
        got, form_count, sub_count = sample_slice(s, pool[s], per_company, used_keys, rnd)
        chosen += got
        report[s] = {
            "pool": len(pool[s]),
            "chosen": len(got),
            "companies": len({c["doc"].ticker for c in got}),
            "forms": dict(form_count),
            **({"subtypes": dict(sub_count)} if s == "S8" else {}),
        }
    return chosen, report


# -- output -----------------------------------------------------------------------------------------------


def main() -> int:
    from dotenv import load_dotenv
    from transformers import AutoTokenizer

    load_dotenv(HERE / ".env")
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B", local_files_only=True)
    rnd = random.Random(SEED)
    docs = load_docs(tok)
    pool = candidates(docs, rnd)
    chosen, report = sample(pool, rnd)

    out_dir = HERE / "dataset"
    pages_used, rows = {}, []
    for i, c in enumerate(
        sorted(chosen, key=lambda c: (SLICES.index(c["slice"]), c["doc"].ticker, c["key"]))
    ):
        doc = c["doc"]
        page_ids = [doc.page_id(p) for p in c["pages"]]
        for p in c["pages"]:
            pages_used[doc.page_id(p)] = {
                "id": doc.page_id(p),
                "ticker": doc.ticker,
                "form": doc.form,
                "accession": doc.accession,
                "document": doc.name,
                "page": p,
                "tokens": doc.page_tokens[p],
                "text": doc.pages[p],
            }
        rows.append(
            {
                "id": f"FE-{i + 1:04d}",
                "slice": c["slice"],
                "subtype": c["subtype"],
                "ticker": doc.ticker,
                "company": doc.company,
                "form": doc.form,
                "accession": doc.accession,
                "document": doc.name,
                "report_date": doc.report_date,
                "question": c["question"],
                "pages": page_ids,
                "page_labels": [p for p in c["pages"]],
                "gold": c["gold"],
            }
        )
    with (out_dir / "questions.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with (out_dir / "pages.jsonl").open("w") as f:
        for p in pages_used.values():
            f.write(json.dumps(p) + "\n")
    stats = {
        "seed": SEED,
        "questions": len(rows),
        "pages": len(pages_used),
        "slices": report,
        "per_company": dict(Counter(r["ticker"] for r in rows).most_common()),
        "per_form": dict(Counter(r["form"] for r in rows)),
        "draft_fingerprint": hashlib.sha256((out_dir / "questions.jsonl").read_bytes()).hexdigest()[:16],
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: v for k, v in stats.items() if k != "per_company"}, indent=2))
    short = [
        s
        for s in SLICES
        if report[s]["chosen"] < PER_SLICE or report[s]["companies"] < MIN_COMPANIES_PER_SLICE
    ]
    if short:
        print(f"\nSLICES SHORT OF THE BAR: {short}")
    return 1 if short else 0


if __name__ == "__main__":
    sys.exit(main())
