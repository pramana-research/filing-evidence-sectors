"""Filing-Evidence Sectors: per-sector analysis (PROTOCOL.md §10, §11; H1).

    uv run --no-project --with statsmodels --with pandas python analyze.py

Reads the frozen questions and every results/sectors/<model>/<setup>/answers.jsonl, and writes
results/sectors/analysis/:
  - sectors.json: for each model x setup x sector (and "all"): accuracy (correct / answerable), confident-wrong
    rate (over all questions), abstention accuracy, outcome mix, each with 95% Wilson intervals (§10, §11);
  - h1.json: H1, logistic regression of correct on sector + model fixed effect, C1, answerable questions,
    standard errors clustered by company; Wald omnibus test of the sector term (§2, §11);
  - sectors.md: the readable tables.
The analysis follows the plan fixed in §10-§11; the code itself was written after the runs (Deviation 3).
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUESTIONS = ROOT / "dataset" / "questions.jsonl"
RESULTS = ROOT / "results"
OUT = RESULTS / "analysis"
SETUPS = ["C1", "C2", "C3"]
SUPPLEMENTARY = {"qwen3-8b"}  # §3: reported, but not pooled and not in H1


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": k / n if n else None, "ci95": wilson(k, n)}


def load_questions() -> dict[str, dict]:
    return {q["id"]: q for q in map(json.loads, QUESTIONS.open())}


def load_answers(model: str, setup: str) -> dict[str, dict]:
    f = RESULTS / model / setup / "answers.jsonl"
    return {r["id"]: r for r in map(json.loads, f.open())} if f.exists() else {}


def metrics(rows: list[tuple[dict, dict]]) -> dict:
    """rows: (question, answer) pairs."""
    oc = Counter(a["outcome"] for _, a in rows)
    answerable = [(q, a) for q, a in rows if q["gold"]["status"] == "found"]
    unanswerable = [(q, a) for q, a in rows if q["gold"]["status"] != "found"]
    return {
        "n": len(rows),
        "accuracy": rate(sum(a["outcome"] == "correct" for _, a in answerable), len(answerable)),
        "confident_wrong": rate(oc["confident_wrong"], len(rows)),
        "abstention_accuracy": rate(sum(a["outcome"] == "abstained_correctly" for _, a in unanswerable),
                                    len(unanswerable)),  # fmt: skip
        "outcomes": dict(oc),
    }


def models() -> list[str]:
    return sorted(p.name for p in RESULTS.iterdir() if p.is_dir() and p.name not in ("analysis", "serve") and (p / "C1" / "answers.jsonl").exists())


def h1(qs: dict[str, dict], ms: list[str]) -> dict:
    import pandas as pd
    import statsmodels.formula.api as smf
    from scipy import stats

    recs = []
    for m in ms:
        for i, a in load_answers(m, "C1").items():
            q = qs[i]
            if q["gold"]["status"] == "found":
                recs.append({"correct": int(a["outcome"] == "correct"), "sector": q["sector"], "model": m,
                             "company": q["ticker"]})  # fmt: skip
    df = pd.DataFrame(recs)
    ref = df.groupby("sector")["correct"].mean().sort_values().index[-1]
    fit = smf.logit(f"correct ~ C(sector, Treatment('{ref}')) + C(model)", df).fit(
        disp=0, cov_type="cluster", cov_kwds={"groups": pd.factorize(df["company"])[0]}
    )
    names = [n for n in fit.params.index if n.startswith("C(sector")]
    w = fit.wald_test(" = 0, ".join(names) + " = 0", scalar=True)
    return {
        "test": "Wald omnibus, sector term; logit(correct ~ sector + model), C1, answerable, SE clustered by company",
        "n": len(df), "clusters": int(df["company"].nunique()), "reference_sector": ref,
        "chi2": float(w.statistic), "df": len(names), "p": float(stats.chi2.sf(w.statistic, len(names))),
        "odds_ratios_vs_reference": {n.split("[T.")[1].rstrip("]"): {
            "or": math.exp(fit.params[n]),
            "ci95": [math.exp(fit.conf_int().loc[n, 0]), math.exp(fit.conf_int().loc[n, 1])]} for n in names},
    }  # fmt: skip


AWAY = {"page header", "table or column header"}  # H2: units stated away from the figure
FIG = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6+": 6}


def tag_frame(qs: dict[str, dict], ms: list[str], setup: str = "C1", ids: set[str] | None = None):
    """Answerable questions (optionally only `ids`), one row per model x question, with the §6 tags."""
    import pandas as pd

    recs = []
    for m in ms:
        for i, a in load_answers(m, setup).items():
            q = qs[i]
            if q["gold"]["status"] != "found" or (ids is not None and i not in ids):
                continue
            t = q["tags"]
            ul = t["units_location"]
            recs.append({
                "model": m, "company": q["ticker"], "sector": q["sector"], "form": q["form"], "outcome": a["outcome"],
                "correct": int(a["outcome"] == "correct"), "cw": int(a["outcome"] == "confident_wrong"),
                # H2 contrast: away (page / table header) vs the reference, unit in the row label
                "units": "away" if ul in AWAY else ul.replace(" ", "_"),
                "figs": FIG[t["figures_on_line"]], "later": int(t["value_position"] == "later"),
                "pos_na": t["value_position"] not in ("first", "later"), "period": t["period_length"].replace(" ", "_"),
                "word_scale": int(bool(t["word_scale"])), "dim": int(bool(t["has_dimension"])),
            })  # fmt: skip
    df = pd.DataFrame(recs)
    return df[~df["pos_na"]].copy()


TAGS = ("C(units, Treatment('in_the_row_label')) + figs + later + C(period, Treatment('3_months')) + word_scale"
        " + dim + C(form) + C(sector) + C(model)")  # fmt: skip


def logit(df, y: str, rhs: str = TAGS):
    import pandas as pd
    import statsmodels.formula.api as smf

    return smf.logit(f"{y} ~ {rhs}", df).fit(disp=0, maxiter=200, cov_type="cluster",
                                              cov_kwds={"groups": pd.factorize(df["company"])[0]})  # fmt: skip


def term(fit, name: str) -> dict:
    lo, hi = fit.conf_int().loc[name]
    return {"term": name, "or": math.exp(fit.params[name]), "ci95": [math.exp(lo), math.exp(hi)],
            "p": float(fit.pvalues[name])}  # fmt: skip


def verdict(t: dict, want_or_above_1: bool) -> str:
    right_way = (t["or"] > 1) == want_or_above_1
    return ("supported (before Holm)" if right_way and t["p"] < 0.05 else
            "opposite direction" if not right_way and t["p"] < 0.05 else "not significant")  # fmt: skip


def h2_h6(qs: dict[str, dict], ms: list[str]) -> dict:
    """§2 H2-H6, §11: one logistic regression on all §6 tags + model fixed effect, SE clustered by company.

    Choices made in code (the protocol names the term, not its coding): units_location is coded with the two
    "away" levels (page header, table or column header) pooled, against the row label as reference; figures on
    the line is ordinal 1-6 (6+ = 6); value position is later vs first (24 items with no position dropped);
    period length has 3 months as reference. H5 refits on 10-Qs only with YTD = 6 or 9 months vs 3 months.
    H6 asks, among word-scale vs other items that were not correct, whether failures are unverifiable-right
    rather than confident-wrong: logit(UR | UR or CW) on word_scale + model.
    """
    df = tag_frame(qs, ms)
    acc, cw = logit(df, "correct"), logit(df, "cw")
    res = {"n": len(df), "clusters": int(df["company"].nunique()), "models": ms, "setup": "C1"}

    t = term(cw, "C(units, Treatment('in_the_row_label'))[T.away]")
    res["H2"] = {"claim": "units stated away from the figure -> higher confident-wrong than units in the row label",
                 **t, "verdict": verdict(t, True),
                 "rates": {u: float(g["cw"].mean()) for u, g in df.groupby("units")},
                 "n_by_level": df["units"].value_counts().to_dict()}  # fmt: skip
    t = term(acc, "figs")
    res["H3"] = {"claim": "accuracy decreases as figures on the line increase (OR per extra figure)", **t,
                 "verdict": verdict(t, False), "rates": {int(k): float(g["correct"].mean()) for k, g in df.groupby("figs")}}
    t = term(acc, "later")
    res["H4"] = {"claim": "accuracy higher when the answer is the line's first figure (OR later vs first)", **t,
                 "verdict": verdict(t, False), "rates": {("later" if k else "first"): float(g["correct"].mean())
                                                         for k, g in df.groupby("later")}}  # fmt: skip

    q10 = df[(df["form"] == "10-Q") & df["period"].isin(["3_months", "6_months", "9_months"])].copy()
    q10["ytd"] = (q10["period"] != "3_months").astype(int)
    f5 = logit(q10, "correct", "ytd + C(units) + figs + later + word_scale + dim + C(sector) + C(model)")
    t = term(f5, "ytd")
    res["H5"] = {"claim": "10-Q: year-to-date (6 or 9 months) accuracy lower than 3 months (OR YTD vs 3 months)",
                 **t, "verdict": verdict(t, False), "n": len(q10),
                 "rates": {("ytd" if k else "3_months"): float(g["correct"].mean()) for k, g in q10.groupby("ytd")}}

    fails = df[df["outcome"].isin(["unverifiable_right", "confident_wrong"])].copy()
    fails["ur"] = (fails["outcome"] == "unverifiable_right").astype(int)
    f6 = logit(fails, "ur", "word_scale + C(model)")
    t = term(f6, "word_scale")
    mix = {}
    for k, g in df.groupby("word_scale"):
        n_fail = int((g["correct"] == 0).sum())
        mix["word_scale" if k else "other"] = {"items": len(g), "not_correct": n_fail,
                                               **{o: int(c) for o, c in g[g["correct"] == 0]["outcome"].value_counts().items()}}  # fmt: skip
    ws = mix["word_scale"]
    res["H6"] = {"claim": "word-scale items fail mainly as unverifiable-right, not confident-wrong", **t,
                 "verdict": verdict(t, True) if ws.get("unverifiable_right", 0) > ws.get("confident_wrong", 0)
                 else ("not supported: CW >= UR within word-scale items" if t["p"] < 0.05 else "not significant"),
                 "n": len(fails), "outcome_mix": mix}  # fmt: skip
    res["all_terms"] = {"accuracy": {n: term(acc, n) for n in acc.params.index if not n.startswith(("C(model", "C(sector", "Intercept"))},
                        "confident_wrong": {n: term(cw, n) for n in cw.params.index if not n.startswith(("C(model", "C(sector", "Intercept"))}}  # fmt: skip
    return res


def mcnemar(a: list[int], b: list[int]) -> dict:
    """Exact McNemar on paired 0/1 outcomes: b01 = 0 under A and 1 under B, b10 = the reverse."""
    from scipy.stats import binomtest

    b01 = sum(1 for x, y in zip(a, b) if not x and y)
    b10 = sum(1 for x, y in zip(a, b) if x and not y)
    p = binomtest(b01, b01 + b10, 0.5).pvalue if b01 + b10 else 1.0
    return {"n": len(a), "a": sum(a), "b": sum(b), "b01": b01, "b10": b10, "p": float(p)}


def holm(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - rank) * ps[i]))
        adj[i] = run
    return adj


def h7(qs: dict[str, dict], ms: list[str]) -> dict:
    """§2 H7, §11: paired exact McNemar per model, C1 vs C2 (all questions) and C1 vs C3 (the C3 subset), on
    confident-wrong (H7) and on accuracy (§11 setup comparisons). Holm within each model's family (its two or
    four comparisons). H7 is judged per model: C3 lowers confident-wrong (significant, lower), C2 does not
    (no significant decrease). The hypothesis-level p used in the Holm correction across H1-H8 is a pooled exact
    McNemar over the reasoning models (discordant pairs summed), a choice made in code (Deviation 3)."""
    res, pooled = {"models": {}}, {"b01": 0, "b10": 0}
    for m in ms:
        c1 = load_answers(m, "C1")
        fam = {}
        for s in ("C2", "C3"):
            other = load_answers(m, s)
            if not other:
                continue
            ids = sorted(set(c1) & set(other))
            ans = [i for i in ids if qs[i]["gold"]["status"] == "found"]
            fam[f"{s}_confident_wrong"] = mcnemar([int(c1[i]["outcome"] == "confident_wrong") for i in ids],
                                                  [int(other[i]["outcome"] == "confident_wrong") for i in ids])  # fmt: skip
            fam[f"{s}_accuracy"] = mcnemar([int(c1[i]["outcome"] == "correct") for i in ans],
                                           [int(other[i]["outcome"] == "correct") for i in ans])  # fmt: skip
        for k, adj in zip(fam, holm([v["p"] for v in fam.values()])):
            fam[k]["p_holm"] = adj
        v = {}
        if "C3_confident_wrong" in fam:
            t = fam["C3_confident_wrong"]
            v["C3_lowers_cw"] = t["b"] < t["a"] and t["p_holm"] < 0.05
            pooled["b01"] += t["b01"]
            pooled["b10"] += t["b10"]
        t = fam["C2_confident_wrong"]
        v["C2_does_not_lower_cw"] = not (t["b"] < t["a"] and t["p_holm"] < 0.05)
        v["C2_raises_cw"] = t["b"] > t["a"] and t["p_holm"] < 0.05
        res["models"][m] = {"tests": fam, "verdict": v}
    from scipy.stats import binomtest

    n = pooled["b01"] + pooled["b10"]
    pooled["p"] = float(binomtest(pooled["b01"], n, 0.5).pvalue)
    res["pooled_C3_confident_wrong"] = pooled
    r = [m for m, d in res["models"].items() if "C3_lowers_cw" in d["verdict"]]
    res["summary"] = {
        "C3_lowers_cw": f"{sum(res['models'][m]['verdict']['C3_lowers_cw'] for m in r)} of {len(r)} reasoning models",
        "C2_does_not_lower_cw": f"{sum(d['verdict']['C2_does_not_lower_cw'] for d in res['models'].values())} of {len(ms)} models",
        "C2_raises_cw": f"{sum(d['verdict']['C2_raises_cw'] for d in res['models'].values())} of {len(ms)} models",
    }  # fmt: skip
    return res


R3_MODELS = ["qwen3.5-9b", "ministral-3-8b", "olmo-3-7b"]  # §12: best, middle (5th of 10), weakest by v1 C1
QUANT = {"qwen3.5-9b-4bit": "qwen3.5-9b", "ministral-3-8b-4bit": "ministral-3-8b", "olmo-3-7b-4bit": "olmo-3-7b"}


def kendall_tau(a: dict[str, float], b: dict[str, float]) -> dict:
    from scipy.stats import kendalltau

    ms = sorted(set(a) & set(b))
    t = kendalltau([a[m] for m in ms], [b[m] for m in ms])
    return {"tau": float(t.statistic), "p": float(t.pvalue), "models": len(ms)}


def paired(c1: dict, other: dict, qs: dict, ids: list[str]) -> dict:
    """Accuracy and confident-wrong, check vs C1 on the same questions, with exact McNemar."""
    ans = [i for i in ids if qs[i]["gold"]["status"] == "found"]
    return {"accuracy": mcnemar([int(c1[i]["outcome"] == "correct") for i in ans],
                                [int(other[i]["outcome"] == "correct") for i in ans]),
            "confident_wrong": mcnemar([int(c1[i]["outcome"] == "confident_wrong") for i in ids],
                                       [int(other[i]["outcome"] == "confident_wrong") for i in ids]),
            "wrong_period_or_column": mcnemar([int(c1[i].get("category") == "wrong_period_or_column") for i in ans],
                                              [int(other[i].get("category") == "wrong_period_or_column") for i in ans]),
            "answerable": len(ans)}  # fmt: skip


def robustness(qs: dict[str, dict], ms: list[str], supp: list[str]) -> dict | None:
    """§12: R1, R2 (all models), R3 (3 models), each vs C1 on the 1,000-question subset; H8 (R1, pooled over the
    main models, discordant pairs summed, as H7); rank stability (Kendall's tau of accuracy rankings, C1 vs R1 and
    vs R2, main models); R3: the share of questions whose outcome changes between the two identical runs;
    robustness of H2-H4 (their terms refitted on the subset under C1, R1 and R2, with a model fixed effect: same direction?);
    §17.3: each 4-bit build vs its full-precision C1 on the subset. Holm within each check, across its models."""
    subset = json.loads((QUESTIONS.parent / "subsets.json").read_text())["c3_and_robustness"]
    sid = set(subset)
    res: dict = {}
    acc_rank: dict[str, dict[str, float]] = {"C1": {}}
    for check in ("R1", "R2", "R3"):
        per = {}
        for m in ms + supp:
            c1, other = load_answers(m, "C1"), load_answers(m, check)
            if not other or len(other) < len(subset):
                continue
            per[m] = paired(c1, other, qs, subset)
            if check == "R3":
                per[m]["outcome_changed"] = rate(sum(c1[i]["outcome"] != other[i]["outcome"] for i in subset), len(subset))
            if m in ms:
                ans = [i for i in subset if qs[i]["gold"]["status"] == "found"]
                acc_rank["C1"][m] = sum(c1[i]["outcome"] == "correct" for i in ans) / len(ans)
                acc_rank.setdefault(check, {})[m] = sum(other[i]["outcome"] == "correct" for i in ans) / len(ans)
        if not per:
            continue
        for key in ("accuracy", "confident_wrong"):
            for m, adj in zip(per, holm([per[m][key]["p"] for m in per])):
                per[m][key]["p_holm"] = adj
        res[check] = {"models": per}
        if check in ("R1", "R2"):
            res[check]["kendall_tau_vs_C1"] = kendall_tau(acc_rank["C1"], acc_rank[check])
    if not res:
        return None
    if "R1" in res:
        main = [m for m in ms if m in res["R1"]["models"]]
        b01 = sum(res["R1"]["models"][m]["wrong_period_or_column"]["b01"] for m in main)
        b10 = sum(res["R1"]["models"][m]["wrong_period_or_column"]["b10"] for m in main)
        from scipy.stats import binomtest

        a = sum(res["R1"]["models"][m]["wrong_period_or_column"]["a"] for m in main)
        b = sum(res["R1"]["models"][m]["wrong_period_or_column"]["b"] for m in main)
        p = float(binomtest(b01, b01 + b10, 0.5).pvalue) if b01 + b10 else 1.0
        res["H8"] = {"claim": "Markdown tables (R1) lower wrong-period-or-column errors vs C1, pooled over main models",
                     "c1": a, "r1": b, "b01": b01, "b10": b10, "p": p, "models": main,
                     "verdict": ("supported (before Holm)" if b < a and p < 0.05 else
                                 "opposite direction" if b > a and p < 0.05 else "not significant")}  # fmt: skip
    # H2-H6 directions under each rendering / prompt, on the subset (main models)
    dirs = {}
    for setup in ["C1"] + [c for c in ("R1", "R2") if c in res]:
        df = tag_frame(qs, [m for m in ms if load_answers(m, setup)], setup, sid)
        rhs = "C(units, Treatment('in_the_row_label')) + figs + later + C(model)"  # the tested terms only (subset)
        acc, cw = logit(df, "correct", rhs), logit(df, "cw", rhs)
        dirs[setup] = {"H2": term(cw, "C(units, Treatment('in_the_row_label'))[T.away]"), "H3": term(acc, "figs"),
                       "H4": term(acc, "later")}  # fmt: skip
    want = {"H2": True, "H3": False, "H4": False}  # odds ratio above 1?
    res["tag_effects_on_subset"] = {
        "terms": dirs,
        "same_direction": {h: all((d[h]["or"] > 1) == w for d in dirs.values()) for h, w in want.items()},
        "note": "H5 (10-Q duration items) and H6 (word-scale failures) are too sparse on the 1,000 subset to refit",
    }
    quant = {}
    for q4, base in QUANT.items():
        c1, other = load_answers(base, "C1"), load_answers(q4, "C1")
        if other and len(other) >= len(subset):
            quant[q4] = {"full_precision": base, **paired(c1, other, qs, subset)}
    if quant:
        for key in ("accuracy", "confident_wrong"):
            for m, adj in zip(quant, holm([quant[m][key]["p"] for m in quant])):
                quant[m][key]["p_holm"] = adj
        res["quantisation_17_3"] = quant
    return res


def pct(r: dict) -> str:
    return "—" if r["rate"] is None else f"{100 * r['rate']:.1f}"


def main() -> None:
    qs = load_questions()
    sectors = sorted({q["sector"] for q in qs.values()})
    ms = models()
    out: dict = {}
    for m in ms:
        for s in SETUPS:
            ans = load_answers(m, s)
            if not ans:
                continue
            rows = [(qs[i], a) for i, a in ans.items()]
            by = defaultdict(list)
            for q, a in rows:
                by[q["sector"]].append((q, a))
            out.setdefault(m, {})[s] = {"all": metrics(rows), **{sec: metrics(by[sec]) for sec in sectors}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sectors.json").write_text(json.dumps(out, indent=1))
    main_ms = [m for m in ms if m not in SUPPLEMENTARY]
    h = h1(qs, main_ms)
    (OUT / "h1.json").write_text(json.dumps(h, indent=1))

    # readable tables: C1 and C2, accuracy and confident-wrong, model x sector
    order = sorted(ms, key=lambda m: -out[m]["C1"]["all"]["accuracy"]["rate"])
    lines = ["# Filing-Evidence Sectors: per-sector results", ""]
    for s in ["C1", "C2"]:
        for key, title in [("accuracy", "accuracy (% of answerable)"), ("confident_wrong", "confident-wrong (% of all)")]:
            lines += [f"## {s} · {title}", "", "| Model | All | " + " | ".join(sectors) + " |",
                      "|---|---|" + "---|" * len(sectors)]  # fmt: skip
            for m in order:
                d = out[m][s]
                lines.append(f"| {m}{' (suppl.)' if m in SUPPLEMENTARY else ''} | **{pct(d['all'][key])}** | " + " | ".join(pct(d[x][key]) for x in sectors) + " |")
            pooled = {x: rate(sum(out[m][s][x][key]["k"] for m in main_ms), sum(out[m][s][x][key]["n"] for m in main_ms))
                      for x in ["all", *sectors]}  # fmt: skip
            lines += [f"| *pooled, 10 main models* | **{pct(pooled['all'])}** | " + " | ".join(pct(pooled[x]) for x in sectors) + " |", ""]
    lines += ["## H1 · accuracy differs across sectors", "",
              f"{h['test']}. n = {h['n']:,}, {h['clusters']} companies. "
              f"χ²({h['df']}) = {h['chi2']:.1f}, p = {h['p']:.2g} (before Holm correction across H1–H8).", "",
              f"| Sector | Odds ratio vs {h['reference_sector']} | 95% CI |", "|---|---|---|"]  # fmt: skip
    for sec, v in sorted(h["odds_ratios_vs_reference"].items(), key=lambda kv: -kv[1]["or"]):
        lines.append(f"| {sec} | {v['or']:.2f} | {v['ci95'][0]:.2f}–{v['ci95'][1]:.2f} |")
    hh = h2_h6(qs, main_ms)
    (OUT / "h2_h6.json").write_text(json.dumps(hh, indent=1))
    lines += ["", "## H2–H6 · what makes a datapoint hard", "",
              f"Logistic regression on all §6 tags + model fixed effect, C1, answerable, SE clustered by company; "
              f"n = {hh['n']:,}, {hh['clusters']} companies. Raw p (Holm across H1–H8 applied once H7, H8 are in).", "",
              "| # | Claim | Odds ratio | 95% CI | p | Verdict |", "|---|---|---|---|---|---|"]  # fmt: skip
    for k in ["H2", "H3", "H4", "H5", "H6"]:
        v = hh[k]
        lines.append(f"| {k} | {v['claim']} | {v['or']:.2f} | {v['ci95'][0]:.2f}–{v['ci95'][1]:.2f} | {v['p']:.2g} | {v['verdict']} |")
    h = h7(qs, main_ms)
    (OUT / "h7.json").write_text(json.dumps(h, indent=1))
    lines += ["", "## H7 · thinking lowers confident-wrong; check + retry does not", "",
              "Paired exact McNemar per model, Holm within each model's family. C2 on all 10,000 questions; "
              "C3 on the 1,000-question subset. Counts are confident-wrong answers (accuracy: correct of answerable).", "",
              "| Model | CW C1 → C2 | p (Holm) | CW C1 → C3 | p (Holm) | Acc C1 → C2 | p (Holm) | Acc C1 → C3 | p (Holm) |",
              "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip

    def cell(t: dict | None) -> str:
        return "— | —" if t is None else f"{t['a']} → {t['b']} | {t['p_holm']:.2g}"

    for m, d in h["models"].items():
        t = d["tests"]
        lines.append(f"| {m} | {cell(t.get('C2_confident_wrong'))} | {cell(t.get('C3_confident_wrong'))} | "
                     f"{cell(t.get('C2_accuracy'))} | {cell(t.get('C3_accuracy'))} |")  # fmt: skip
    s = h["summary"]
    pc = h["pooled_C3_confident_wrong"]
    lines += ["", f"C3 lowers confident-wrong: **{s['C3_lowers_cw']}** (pooled: {pc['b10']} answers stop being "
              f"confident-wrong, {pc['b01']} start; p = {pc['p']:.2g}). C2 does not lower it: **{s['C2_does_not_lower_cw']}**; "
              f"C2 raises it significantly: **{s['C2_raises_cw']}**."]  # fmt: skip

    rb = robustness(qs, main_ms, [m for m in ms if m in SUPPLEMENTARY])
    if rb:
        (OUT / "robustness.json").write_text(json.dumps(rb, indent=1))
        lines += ["", "## Robustness checks (§12), each vs C1 on the 1,000-question subset", ""]
        for check in ("R1", "R2", "R3"):
            if check not in rb:
                continue
            lines += [f"### {check}", "", "| Model | Acc C1 → " + check + " | p (Holm) | CW C1 → " + check + " | p (Holm) |"
                      + (" outcome changed |" if check == "R3" else ""), "|---|---|---|---|---|" + ("---|" if check == "R3" else "")]  # fmt: skip
            for m, d in rb[check]["models"].items():
                row = (f"| {m} | {d['accuracy']['a']} → {d['accuracy']['b']} | {d['accuracy']['p_holm']:.2g} | "
                       f"{d['confident_wrong']['a']} → {d['confident_wrong']['b']} | {d['confident_wrong']['p_holm']:.2g} |")
                if check == "R3":
                    row += f" {pct(d['outcome_changed'])}% |"
                lines.append(row)
            if "kendall_tau_vs_C1" in rb[check]:
                t = rb[check]["kendall_tau_vs_C1"]
                lines.append(f"\nRank stability: Kendall's τ = {t['tau']:.2f} (p = {t['p']:.2g}, {t['models']} models).")
            lines.append("")
        if "H8" in rb:
            h8 = rb["H8"]
            lines.append(f"**H8:** wrong-period-or-column errors {h8['c1']} (C1) → {h8['r1']} (R1); p = {h8['p']:.2g}: {h8['verdict']}.")
        te = rb["tag_effects_on_subset"]["same_direction"]
        lines.append("Tag effects (H2–H4) keep their direction under C1, R1, R2 on the subset: "
                     + ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in te.items()) + ".")
        if "quantisation_17_3" in rb:
            lines += ["", "## §17.3 · 4-bit vs full precision (C1, subset; supplementary, exploratory)", "",
                      "| 4-bit build | Acc full → 4-bit | p (Holm) | CW full → 4-bit | p (Holm) |", "|---|---|---|---|---|"]
            for m, d in rb["quantisation_17_3"].items():
                lines.append(f"| {m} | {d['accuracy']['a']} → {d['accuracy']['b']} | {d['accuracy']['p_holm']:.2g} | "
                             f"{d['confident_wrong']['a']} → {d['confident_wrong']['b']} | {d['confident_wrong']['p_holm']:.2g} |")

    ps = {"H1": json.loads((OUT / "h1.json").read_text())["p"], **{k: hh[k]["p"] for k in ["H2", "H3", "H4", "H5", "H6"]},
          "H7": pc["p"]}  # fmt: skip
    if rb and "H8" in rb:
        ps["H8"] = rb["H8"]["p"]
    adj = dict(zip(ps, holm(list(ps.values()))))
    span = "H1–H8" if "H8" in ps else "H1–H7; H8 pending: needs R1"
    lines += ["", f"## Holm correction across the hypotheses ({span})", "",
              "| # | raw p | Holm p |", "|---|---|---|"] + \
             [f"| {k} | {ps[k]:.2g} | {adj[k]:.2g} |" for k in ps]  # fmt: skip
    (OUT / "holm.json").write_text(json.dumps({"raw": ps, "holm": adj, "over": span}, indent=1))
    (OUT / "sectors.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
