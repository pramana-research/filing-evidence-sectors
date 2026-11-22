"""The Filing-Evidence checker (PROTOCOL.md §7), outcomes (§8), error taxonomy (§9) and summary metrics.

No model and no network: pure functions over a question, its pages and a reply. The runner (runner.py) and the
report use only these, so every number in the results comes from one place.

    check(reply_text, question, pages)  -> Graded  (parsed answer, failed check, outcome, category)
    summarize(graded_rows)              -> dict    (headline and per-slice metrics with Wilson intervals)
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass

# -- parsing -----------------------------------------------------------------------------------------------

_THINK = re.compile(r"<think>.*?(</think>|$)", re.S)
_FENCE = re.compile(r"```(?:json)?", re.I)


def parse_reply(text: str) -> dict | None:
    """The JSON object in a reply: reasoning blocks and code fences removed, then the first object that parses
    and has a "status" field. None if there isn't one."""
    text = _FENCE.sub("", _THINK.sub("", text or ""))
    starts = [m.start() for m in re.finditer(r"\{", text)]
    decoder = json.JSONDecoder()
    for s in starts:
        try:
            obj, _ = decoder.raw_decode(text[s:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "status" in obj:
            return obj
    return None


def to_number(x) -> float | None:
    """A model's value as a number: accepts 1234, "1,234", "$1,234", "(1,234)", "-1,234", "3.96%"."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, int | float):
        return float(x)
    s = str(x).strip().replace("$", "").replace(",", "").replace("%", "").replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def to_page(x) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    m = re.fullmatch(r"\s*(?:page\s*)?(\d+)\s*", str(x), re.I)
    return int(m.group(1)) if m else None


def scale_factor(text) -> float:
    """The multiplier a units statement implies ("in millions" -> 1e6); 1 when none is given."""
    s = str(text or "").lower()
    for word, f in (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3)):
        if word in s:
            return f
    return 1.0


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


_SPAN_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


def numbers_in(span: str) -> list[float]:
    """The figures displayed in a line: thousands separators, "$", "%" and parentheses ignored."""
    return [float(n.replace(",", "")) for n in _SPAN_NUMBER.findall(span)]


def same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


# -- grading -----------------------------------------------------------------------------------------------

OUTCOMES = [
    "correct",
    "confident_wrong",
    "caught_wrong",
    "unverifiable_right",
    "missed",
    "abstained_correctly",
    "invented",
    "invalid",
]
CATEGORIES = [
    "wrong_line_quoted",
    "wrong_page_cited",
    "span_not_verbatim",
    "scale_or_unit",
    "wrong_period_or_column",
    "wrong_item",
    "invented_on_s8",
    "missed",
    "invalid_format",
]


@dataclass
class Graded:
    answer: dict | None
    failed_check: str | None  # first failed check of §7: parse | page | span | value; None if all pass
    outcome: str
    category: str | None  # §9, for every non-correct outcome except abstained_correctly
    value_matches_gold: bool | None
    # secondary (§8, added 2026-11-16): the checks pass and the digits equal the gold as displayed, whatever
    # scale the model stated. Separates finding the number from reading its units header.
    right_ignoring_scale: bool | None = None


def failed_check(answer: dict | None, question: dict, pages: dict[str, str]) -> str | None:
    """§7. None when the answer passes. A not_found answer has nothing to check beyond parsing."""
    if answer is None or answer.get("status") not in ("found", "not_found"):
        return "parse"
    if answer["status"] == "not_found":
        return None
    value = to_number(answer.get("value"))
    if value is None:
        return "parse"
    page = to_page(answer.get("page"))
    labels = dict(zip(question["page_labels"], question["pages"], strict=True))
    if page not in labels:
        return "page"
    span = norm_ws(str(answer.get("span") or ""))
    if not span or span not in norm_ws(pages[labels[page]]):
        return "span"
    if not any(same(abs(value), n) for n in numbers_in(span)):
        return "value"
    return None


def value_matches_gold(answer: dict, gold: dict) -> bool:
    """§8: equal to gold after scale; per-share and percent values compared as displayed. Sign not graded."""
    v = to_number(answer.get("value"))
    if v is None:
        return False
    v = abs(v)
    shown, full = abs(gold["shown_value"]), abs(gold["value"])
    if gold["unit"] in ("USD per share", "pure"):
        return same(v, shown) or same(v, full)  # as displayed (or the plain fraction for percentages)
    return same(v * scale_factor(answer.get("scale")), full)


def _category_wrong_value(answer: dict, gold: dict) -> str:
    v = abs(to_number(answer.get("value")) or 0.0)
    shown, full = abs(gold["shown_value"]), abs(gold["value"])
    scaled = v * scale_factor(answer.get("scale"))
    powers = [k for k in range(-12, 13) if k]
    if same(v, shown) or any(same(scaled * 10**k, full) or same(v * 10**k, shown) for k in powers):
        return "scale_or_unit"  # the right digits, wrong multiplier or decimal point ("273" for 2.73)
    if any(any(same(v, n) for n in numbers_in(e["line"])) for e in gold.get("evidence", [])):
        return "wrong_period_or_column"  # another figure of the answer's own row
    return "wrong_item"


def _category_bad_evidence(check: str, answer: dict, question: dict, pages: dict[str, str]) -> str:
    if check == "page":
        return "wrong_page_cited"
    if check == "span":
        span = norm_ws(str(answer.get("span") or ""))
        on_other = span and any(span in norm_ws(pages[p]) for p in question["pages"])
        return "wrong_page_cited" if on_other else "span_not_verbatim"
    gold = question["gold"]
    span = norm_ws(str(answer.get("span") or ""))
    if any(same(abs(gold["shown_value"]), n) for n in numbers_in(span)):
        return "scale_or_unit"  # right line, value restated in other units ("8,600 in thousands")
    return "wrong_line_quoted"  # check == "value": real line, but not the one with the number


def check(reply_text: str, question: dict, pages: dict[str, str]) -> Graded:
    answer = parse_reply(reply_text)
    fc = failed_check(answer, question, pages)
    gold = question["gold"]
    if fc == "parse":
        return Graded(answer, fc, "invalid", "invalid_format", None)
    if gold["status"] == "not_found":
        if answer["status"] == "not_found":
            return Graded(answer, fc, "abstained_correctly", None, None)
        return Graded(answer, fc, "invented", "invented_on_s8", None)
    if answer["status"] == "not_found":
        return Graded(answer, fc, "missed", "missed", False)
    right = value_matches_gold(answer, gold)
    if right and fc is None:
        return Graded(answer, fc, "correct", None, True, True)
    if right:
        return Graded(
            answer, fc, "unverifiable_right", _category_bad_evidence(fc, answer, question, pages), True
        )
    outcome = "confident_wrong" if fc is None else "caught_wrong"
    digits = fc is None and same(abs(to_number(answer.get("value")) or 0.0), abs(gold["shown_value"]))
    return Graded(answer, fc, outcome, _category_wrong_value(answer, gold), False, digits)


def retry_message(check_name: str, answer: dict | None, question: dict, templates: dict[str, str]) -> str:
    """C2's feedback: which check failed (fixed text, prompts/v1_retry.txt), never the gold."""
    page = to_page((answer or {}).get("page"))
    listed = ", ".join(str(p) for p in sorted(question["page_labels"]))
    msg = templates[check_name].replace("{page}", str(page)).replace("{pages}", listed)
    return f"{msg} {templates['footer']}"


def load_retry_templates(path) -> dict[str, str]:
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            k, v = line.rstrip("\n").split("|", 1)
            out[k] = v
    return out


# -- metrics -----------------------------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else float("nan"), "ci95": [lo, hi]}


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, math.ceil(q * len(xs)) - 1)]


def summarize(rows: list[dict]) -> dict:
    """rows: one per question, with keys slice, outcome, category, retried, completion_tokens, seconds."""
    answerable = [r for r in rows if r["slice"] != "S8"]
    s8 = [r for r in rows if r["slice"] == "S8"]
    out = {
        "n": len(rows),
        "accuracy": _rate(sum(r["outcome"] == "correct" for r in answerable), len(answerable)),
        "confident_wrong": _rate(sum(r["outcome"] == "confident_wrong" for r in rows), len(rows)),
        "abstention_accuracy": _rate(sum(r["outcome"] == "abstained_correctly" for r in s8), len(s8)),
        "outcomes": {o: sum(r["outcome"] == o for r in rows) for o in OUTCOMES},
        "categories": {c: sum(r["category"] == c for r in rows) for c in CATEGORIES},
        "by_slice": {},
        "retry_rate": _rate(sum(bool(r.get("retried")) for r in rows), len(rows)),
        "completion_tokens": {
            "mean": sum(r["completion_tokens"] for r in rows) / max(1, len(rows)),
            "p95": _pct([r["completion_tokens"] for r in rows], 0.95),
        },
        "seconds": {
            "mean": sum(r["seconds"] for r in rows) / max(1, len(rows)),
            "p95": _pct([r["seconds"] for r in rows], 0.95),
        },
    }
    for s in sorted({r["slice"] for r in rows}):
        rs = [r for r in rows if r["slice"] == s]
        good = "abstained_correctly" if s == "S8" else "correct"
        out["by_slice"][s] = _rate(sum(r["outcome"] == good for r in rs), len(rs))
    # coverage at zero confident-wrong: answering only when the checker passes, how much is answered correctly
    out["accuracy_ignoring_scale"] = _rate(
        sum(bool(r.get("right_ignoring_scale")) for r in answerable), len(answerable)
    )
    passed = [r for r in answerable if r["outcome"] in ("correct", "confident_wrong")]
    out["checker_pass_precision"] = _rate(sum(r["outcome"] == "correct" for r in passed), len(passed))
    return out


def as_dict(g: Graded) -> dict:
    return asdict(g)
