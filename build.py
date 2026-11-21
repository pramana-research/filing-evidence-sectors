"""Build the Filing-Evidence Sectors questions (PROTOCOL.md §4-§8): 10 sectors x 1,000 questions.

Every rule that decides whether a fact can become a question, how it is worded and which pages are shown is
v1's, imported unchanged from ../../builder.py (answerability, wording, slices, shown pages, gold, S8 kinds).
What is new here is only what the sectors protocol adds:
  - sampling per sector to the §5 targets, about 100 questions per company (at most 130), each slice drawn
    from at least 7 of the sector's 10 companies, at most 3 questions per XBRL concept per filing;
  - no fact used by a v1 question (§4.4), and no v1 question text;
  - difficulty tags on every question (§6);
  - the stratified 1,000-question subset for C3 and the robustness checks (§8, §12), drawn with its own seed.

Reads sets/sectors/dataset/manifest.json (from fetch.py) and the filings in DATA_DIR; writes, in
sets/sectors/dataset/:
    questions.jsonl   one question per line (v1's fields, plus sector and tags)
    pages.jsonl       the text of every page used
    subsets.json      the ids of the stratified 1,000-question subset
    stats.json        counts per sector, slice, company and form, pool sizes, and any shortfall

    uv run --extra build python sets/sectors/build.py
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import builder as v1  # noqa: E402
from builder import SLICES, Doc  # noqa: E402

SEED = 20261121
SUBSET_SEED = 20261122
TARGETS = {"S1": 120, "S2": 120, "S3": 120, "S4": 160, "S5": 120, "S6": 120, "S7": 140, "S8": 100}
SUBSET_PER_SECTOR = {"S1": 12, "S2": 12, "S3": 12, "S4": 16, "S5": 12, "S6": 12, "S7": 14, "S8": 10}
PER_SECTOR = 1000
MAX_PER_COMPANY = 130
MIN_COMPANIES_PER_SLICE = 7
MAX_PER_CONCEPT_PER_FILING = 3
OUT = HERE / "dataset"


# -- documents --------------------------------------------------------------------------------------------


def load_docs(tok) -> list[Doc]:
    """As builder.load_docs, for the sectors manifest and names."""
    from collections import Counter as C

    from ixbrl import read_document_set, read_labels
    from paths import data_dir

    manifest = json.loads((OUT / "manifest.json").read_text())
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
            usd_per_page = C(
                x.occurrences[0].page
                for x in doc.facts
                if x.unit == "iso4217:USD" and not doc.contexts[x.context].dims
            )
            doc.statement_pages = {
                i for i, p in enumerate(doc.pages) if v1.is_statement_page(p, usd_per_page[i])
            }
            doc.notes_pages = set(v1.notes_range(doc.pages, min(doc.statement_pages, default=-1)))
            doc.page_tokens = [v1.tokens(p, tok) for p in doc.pages]
            doc.index()
            docs.append(doc)
        print(f"read {f['ticker']:5s} {f['form']}", flush=True)
    return docs


# -- v1 exclusion (§4.4) ----------------------------------------------------------------------------------


def fact_key(accession: str, gold: dict) -> str:
    """The same key builder.candidates gives a candidate, rebuilt from a v1 question's gold answer."""
    p = gold.get("period") or {}
    return f"{accession}:{gold.get('concept')}:{p.get('start')}:{p.get('end')}:{p.get('instant')}:" + str(
        sorted((gold.get("dims") or {}).items())
    )


def v1_exclusions() -> tuple[set[str], set[str]]:
    keys, texts = set(), set()
    for line in (ROOT / "dataset" / "questions.jsonl").open():
        q = json.loads(line)
        texts.add(q["question"])
        if q["gold"]["status"] == "found":
            keys.add(fact_key(q["accession"], q["gold"]))
    return keys, texts


# -- difficulty tags (§6) ---------------------------------------------------------------------------------

_SCALE_WORD = re.compile(r"\b(thousand|million|billion)s?\b", re.I)
_UNITS_STATEMENT = re.compile(
    r"\(?\s*(in|amounts in|dollars in|\$ in)\s+(thousands|millions|billions)|"
    r"\b(thousands|millions|billions)\s+of\s+(u\.s\.\s+)?dollars|\(\s*(thousands|millions|billions)\b",
    re.I,
)


_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}\b|(?<![$\d,.])\b(19|20)\d{2}\b(?![,.]\d)",
    re.I,
)


def figures_after_label(line: str) -> list[str]:
    """The figures in a line after its label. Dates and bare years ("as of December 27, 2025", "Fiscal 2025")
    belong to the label, not to the figures."""
    masked = _DATE.sub(
        lambda m: "x" * len(m.group(0)), v1._WORDY_PAREN.sub(lambda m: " " * len(m.group(0)), line)
    )
    m = v1._FIRST_FIGURE.search(masked)
    if not m:
        return []
    return [x.group(0) for x in v1._FIGURE.finditer(masked[m.start() :])]


def digits(s: str) -> str:
    return re.sub(r"[^0-9.]", "", s).lstrip("0") or "0"


def units_location(page: str, line: str, gold: dict) -> str:
    """Where a reader learns the figure's units: in the row label, in the line, in its table's header, in the
    page header, or nowhere (a plain number)."""
    first = v1.figure_start(line)
    label = line[:first] if first else line
    if gold["unit"] in ("USD per share", "pure") and re.search(
        r"per\s+share|%|percent|ratio|rate", label, re.I
    ):
        return "in the row label"
    if _SCALE_WORD.search(line) or "%" in line or re.search(r"per\s+share", line, re.I):
        return "in the line"
    lines = page.split("\n")
    try:
        i = lines.index(line)
    except ValueError:
        i = len(lines)
    if any(_UNITS_STATEMENT.search(x) for x in lines[max(0, i - 40) : i]):
        if any(_UNITS_STATEMENT.search(x) for x in lines[: min(8, i)]):
            return "page header"
        return "table or column header"
    return (
        "none" if gold["scale"] in (0, None) else "page header" if _UNITS_STATEMENT.search(page) else "none"
    )


def period_length(period: dict) -> str:
    if period.get("instant"):
        return "instant"
    d = v1.days(period.get("start"), period.get("end")) or 0
    return "3 months" if d < 120 else "6 months" if d < 200 else "9 months" if d < 300 else "12 months"


def tags(c: dict, sector: str) -> dict:
    g = c["gold"]
    t = {"sector": sector, "form": c["doc"].form}
    if g["status"] != "found":
        return t
    ev = g["evidence"][0]
    page_no = int(ev["page"].rsplit("#p", 1)[1])
    page_text = c["doc"].pages[page_no]
    line = ev["line"]
    figs = figures_after_label(line)
    target = digits(g["display"])
    pos = next((i for i, f in enumerate(figs) if digits(f) == target), None)
    n = len(figs) if figs else 1
    t.update(
        {
            "units_location": units_location(page_text, line, g),
            "figures_on_line": "6+" if n >= 6 else str(n),
            "value_position": "first" if pos == 0 else "later" if pos else "n/a",
            "period_length": period_length(g["period"]),
            "word_scale": bool(
                re.search(re.escape(g["display"]) + r"\s*(thousand|million|billion)", line, re.I)
            ),
            "has_dimension": bool(g.get("dims")),
        }
    )
    return t


# -- sampling (§5) ----------------------------------------------------------------------------------------


FILL_ORDER = ["S4", "S1", "S2", "S3"]  # §14 deviation 1: the slices that fill a sector up to 1,000
FILL_STEP = 20


def sample_slice(s, cands, target, per_company, per_concept, used, seen, rnd, even_s8=True):
    """builder.sample_slice's rules (companies take turns in a fixed random order; the scarcer form first; S8
    split evenly across its kinds), with this protocol's target, company cap and per-concept-per-filing cap.
    One question per item per *filing* (§14 deviation 1; v1: per company). `seen` holds the items already
    used in this sector and slice; with even_s8=False, S8 takes any kind (the top-up after the even split)."""
    queues = defaultdict(lambda: defaultdict(list))
    for c in cands:
        queues[c["doc"].ticker][c["doc"].form].append(c)
    for forms in queues.values():
        for lst in forms.values():
            rnd.shuffle(lst)
    companies = sorted(queues)
    rnd.shuffle(companies)
    got, form_count, sub_count = [], Counter(), Counter()
    sub_target = {k: target // 4 + (1 if i < target % 4 else 0) for i, k in enumerate("abcd")}

    def take(t, form):
        lst = queues[t][form]
        while lst:
            c = lst.pop()
            g = c["gold"]
            item = (
                c["doc"].accession,
                g.get("concept"),
                c["subtype"],
                str(sorted((g.get("dims") or {}).items())),
            )
            concept_key = (c["doc"].accession, g.get("concept"))
            if c["key"] in used or c["question"] in used or item in seen:
                continue
            if per_concept[concept_key] >= MAX_PER_CONCEPT_PER_FILING:
                continue
            if s == "S8" and even_s8 and sub_count[c["subtype"]] >= sub_target[c["subtype"]]:
                continue
            got.append(c)
            used.update((c["key"], c["question"]))
            seen.add(item)
            per_company[t] += 1
            per_concept[concept_key] += 1
            form_count[form] += 1
            sub_count[c["subtype"]] += 1
            return True
        return False

    progress = True
    while len(got) < target and progress:
        progress = False
        for t in companies:
            if len(got) >= target or per_company[t] >= MAX_PER_COMPANY:
                continue
            order = sorted(("10-K", "10-Q"), key=lambda f: (form_count[f], f))
            if take(t, order[0]) or take(t, order[1]):
                progress = True
    return got, form_count, sub_count


def main() -> int:
    from dotenv import load_dotenv
    from transformers import AutoTokenizer

    load_dotenv(ROOT / ".env")
    spec = yaml.safe_load((HERE / "companies.yaml").read_text())
    sector_of = {t: s for s, ts in spec["sectors"].items() for t in ts}
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B", local_files_only=True)
    rnd = random.Random(SEED)
    docs = load_docs(tok)
    pool = v1.candidates(docs, rnd)
    v1_keys, v1_texts = v1_exclusions()
    excluded = Counter()
    for s in SLICES:
        kept = []
        for c in pool[s]:
            if c["key"] in v1_keys or c["question"] in v1_texts:
                excluded[s] += 1
            else:
                kept.append(c)
        pool[s] = kept

    chosen, report, used = [], {}, set()
    for sector in spec["sectors"]:
        per_company, per_concept = Counter(), Counter()
        spool = {s: [c for c in pool[s] if sector_of.get(c["doc"].ticker) == sector] for s in SLICES}
        report[sector] = {}
        seen = {s: set() for s in SLICES}
        picked = {s: [] for s in SLICES}
        for s in sorted(SLICES, key=lambda s: len(spool[s])):  # scarcest slice first, as in v1
            got, _, _ = sample_slice(s, spool[s], TARGETS[s], per_company, per_concept, used, seen[s], rnd)
            picked[s] += got
        # §14 deviation 1: S8 kinds are split evenly where possible, then topped up from any kind
        if len(picked["S8"]) < TARGETS["S8"]:
            got, _, _ = sample_slice(
                "S8", spool["S8"], TARGETS["S8"] - len(picked["S8"]), per_company, per_concept, used,
                seen["S8"], rnd, even_s8=False,
            )  # fmt: skip
            picked["S8"] += got
        # §14 deviation 1: fill the sector to 1,000 from the plentiful slices, in turn
        filled = Counter()
        progress = True
        while sum(map(len, picked.values())) < PER_SECTOR and progress:
            progress = False
            for s in FILL_ORDER:
                need = PER_SECTOR - sum(map(len, picked.values()))
                if need <= 0:
                    break
                got, _, _ = sample_slice(
                    s, spool[s], min(FILL_STEP, need), per_company, per_concept, used, seen[s], rnd
                )
                picked[s] += got
                filled[s] += len(got)
                progress = progress or bool(got)
        for s in SLICES:
            got = picked[s]
            for c in got:
                c["sector"] = sector
            chosen += got
            report[sector][s] = {
                "pool": len(spool[s]),
                "chosen": len(got),
                "target": TARGETS[s],
                "filled_beyond_target": filled[s],
                "companies": len({c["doc"].ticker for c in got}),
                "forms": dict(Counter(c["doc"].form for c in got)),
                **({"subtypes": dict(Counter(c["subtype"] for c in got))} if s == "S8" else {}),
            }

    OUT.mkdir(exist_ok=True)
    pages_used, rows = {}, []
    order = list(spec["sectors"])
    chosen.sort(key=lambda c: (order.index(c["sector"]), SLICES.index(c["slice"]), c["doc"].ticker, c["key"]))
    for i, c in enumerate(chosen):
        doc = c["doc"]
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
                "id": f"FES-{i + 1:05d}",
                "sector": c["sector"],
                "slice": c["slice"],
                "subtype": c["subtype"],
                "ticker": doc.ticker,
                "company": doc.company,
                "form": doc.form,
                "accession": doc.accession,
                "document": doc.name,
                "report_date": doc.report_date,
                "question": c["question"],
                "pages": [doc.page_id(p) for p in c["pages"]],
                "page_labels": list(c["pages"]),
                "gold": c["gold"],
                "tags": tags(c, c["sector"]),
            }
        )
    with (OUT / "questions.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with (OUT / "pages.jsonl").open("w") as f:
        for p in pages_used.values():
            f.write(json.dumps(p) + "\n")

    # the stratified subset for C3 and the robustness checks (§8, §12), drawn before any run
    srnd = random.Random(SUBSET_SEED)
    subset = []
    for sector in spec["sectors"]:
        for s, k in SUBSET_PER_SECTOR.items():
            ids = [r["id"] for r in rows if r["sector"] == sector and r["slice"] == s]
            subset += sorted(srnd.sample(ids, min(k, len(ids))))
    (OUT / "subsets.json").write_text(
        json.dumps({"seed": SUBSET_SEED, "c3_and_robustness": subset, "size": len(subset)}, indent=2) + "\n"
    )

    short = [
        f"{sector}: {n} questions"
        for sector, n in Counter(r["sector"] for r in rows).items()
        if n < PER_SECTOR
    ]
    below_target = [
        f"{sector} {s}: {v['chosen']}/{v['target']} from {v['companies']} companies"
        for sector, sl in report.items()
        for s, v in sl.items()
        if v["chosen"] < v["target"] or v["companies"] < MIN_COMPANIES_PER_SLICE
    ]
    stats = {
        "seed": SEED,
        "questions": len(rows),
        "pages": len(pages_used),
        "per_sector": dict(Counter(r["sector"] for r in rows)),
        "slices": report,
        "excluded_as_v1": dict(excluded),
        "per_company": dict(Counter(r["ticker"] for r in rows).most_common()),
        "per_form": dict(Counter(r["form"] for r in rows)),
        "tags": {
            k: dict(Counter(str(r["tags"].get(k)) for r in rows if r["gold"]["status"] == "found"))
            for k in ("units_location", "figures_on_line", "value_position", "period_length", "word_scale")
        },
        "subset": len(subset),
        "short": short,
        "slices_below_target": below_target,
        "draft_fingerprint": hashlib.sha256((OUT / "questions.jsonl").read_bytes()).hexdigest()[:16],
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps({k: v for k, v in stats.items() if k not in ("per_company", "slices")}, indent=2))
    if below_target:
        print(
            "\nSlices below their §5 target (filled from S1-S4, §14 deviation 1):\n  "
            + "\n  ".join(below_target)
        )
    if short:
        print("\nSECTORS SHORT OF 1,000 (§5: fill from reserves, log in §14):\n  " + "\n  ".join(short))
    return 1 if short else 0


if __name__ == "__main__":
    sys.exit(main())
