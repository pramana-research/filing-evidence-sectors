"""Static SVG charts for the Sectors report. Every value comes from report/build/data.json (report/data.py).

Palette and primitives are Filing-Evidence v1's (report/_prims.py, copied unchanged), so the two papers match:
outcomes good #2E3F9E → bad #B3302A; setups C1 #8F9BDD · C2 #5466C4 · C3 #1F2C73. Marks carry colour; text uses
ink tokens; every mark has a <title> (hover).
"""

from __future__ import annotations

import math
from datetime import datetime
from html import escape

from _prims import AXIS, BAD, GOOD, GRID, INK, INK2, MUTED, NAMES, SETUP, SURF, dot, hbar, legend, svg, t

NAMES = {**NAMES, "qwen3.5-9b-4bit": "Qwen3.5-9B 4-bit", "ministral-3-8b-4bit": "Ministral-3-8B 4-bit",
         "olmo-3-7b-4bit": "OLMo-3-7B 4-bit"}  # fmt: skip
SHORT = {"Banks": "Banks", "Energy (power and utilities)": "Utilities", "Healthcare": "Health",
         "Insurance": "Insurance", "Media": "Media", "Metals and mining": "Metals", "Oil and gas": "Oil & gas",
         "Real estate": "Real est.", "Technology": "Tech", "Telecom": "Telecom"}  # fmt: skip
R1_STRICT, R1_FREE = "#C9CEDF", "#5466C4"


def _seq(v):
    a, z = (0xEE, 0xF0, 0xFA), (0x1F, 0x2C, 0x73)
    return "#" + "".join(f"{round(a[i] + (z[i] - a[i]) * v):02X}" for i in range(3))


def _acc(d, m, s="C1", sec="all"):
    return d["sectors_table"][m][s][sec]["accuracy"]


def _order(d, models=None):
    models = models or d["models"]
    return sorted(models, key=lambda m: -_acc(d, m)["rate"])


def _label(m, d):
    return NAMES[m] + (" *" if m in d["supplementary"] else "")


def _grid_x(b, X, vals, y0, y1, fmt=str, zero=None):
    for v in vals:
        b.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{y0}" y2="{y1}" stroke="{AXIS if v == zero else GRID}"/>')
        b.append(t(X(v), y1 + 16, fmt(v), 11, "middle", MUTED))


# -- 1 · timeline ---------------------------------------------------------------------------------------------


def timeline(d):
    tl = d["timeline"]
    steps = [("protocol", "Protocol v1.0 committed", "hypotheses H1–H8 fixed"),
             ("freeze", "10,000 questions frozen", "fingerprint 9a007d80"),
             ("runs_start", "Model runs start", "C1, then C2, then C3"),
             ("main_runs_done", "Main runs done", "226,000 answers"),
             ("robustness_fixed", "R1–R3 details fixed", "Deviation 5, before any R run"),
             ("robustness_done", "Robustness runs done", "28,000 more answers")]  # fmt: skip
    W, H, L, R = 760, 230, 95, 95
    X = lambda v: L + v / (len(steps) - 1) * (W - L - R)  # noqa: E731
    b = [f'<line x1="{L}" x2="{W - R}" y1="110" y2="110" stroke="{AXIS}" stroke-width="2"/>']
    for i, (k, a, c) in enumerate(steps):
        when = datetime.fromisoformat(tl[k]).strftime("%d %b %H:%M")
        b.append(dot(X(i), 110, GOOD if i < 2 else SETUP["C2"], f"{a}: {when} IST", 6))
        y0 = 58 if i % 2 == 0 else 138  # three lines above (even steps) or below (odd steps)
        b.append(t(X(i), y0, a, 12, "middle", INK, 600))
        b.append(t(X(i), y0 + 14, when, 10.5, "middle", MUTED))
        b.append(t(X(i), y0 + 28, c, 10.5, "middle", MUTED))
    b.append(t(30, 218, "All times IST. The protocol and freeze commits are public in pramana-research/filing-evidence.",
               10.5, "start", MUTED))
    return svg(W, H, "".join(b), "Study timeline",
               "The protocol and the frozen dataset were committed before any model ran; the robustness details "
               "were fixed before any robustness run.")


# -- 2 · model x sector heat map ------------------------------------------------------------------------------


def sector_heatmap(d, setup="C1"):
    models, secs = _order(d), d["sectors"]
    W, L, T, cw_, ch = 760, 178, 52, 52, 26
    H = T + len(models) * ch + 30
    b = []
    for jx, s in enumerate(secs):
        b.append(t(L + jx * cw_ + cw_ / 2, T - 12, SHORT[s], 11, "middle", INK, 600))
    b.append(t(L + len(secs) * cw_ + 30, T - 12, "All", 11, "middle", INK, 700))
    for i, m in enumerate(models):
        y = T + i * ch
        b.append(t(L - 10, y + ch / 2 + 4, _label(m, d), 12.5, "end", INK, 500))
        for jx, s in enumerate(secs + ["all"]):
            r = _acc(d, m, setup, s)
            v = max(0.0, min(1.0, (r["rate"] - 0.1) / 0.85))
            x = L + jx * cw_ + (8 if s == "all" else 0)
            b.append(f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{cw_ - 2}" height="{ch - 2}" rx="3" '
                     f'fill="{_seq(v)}"><title>{escape(NAMES[m])}, {escape(s)}: {100 * r["rate"]:.1f}% '
                     f'({r["k"]} of {r["n"]})</title></rect>')
            b.append(t(x + cw_ / 2, y + ch / 2 + 4, f"{100 * r['rate']:.0f}", 11, "middle",
                       "#FFFFFF" if v > 0.5 else INK, 600 if s == "all" else 500, cls="num"))
    b.append(t(L, H - 6, "Accuracy (% of answerable), plain setup. * supplementary model.", 10.5, "start", MUTED))
    return svg(W, H, "".join(b), "Accuracy by model and sector",
               "Rows are models, columns are sectors; darker is more accurate. Rows differ far more than columns.")


# -- 3 · sector odds ratios (H1) -------------------------------------------------------------------------------


def _forest(rows, title, desc, lo=0.3, hi=3.0, ref_label="", note="", W=760, L=250):
    """rows: (label, or, (ci_lo, ci_hi), tip, colour). Log-scale odds ratios with a line at 1."""
    T, rowh = 34, 30
    H = T + len(rows) * rowh + 46
    X = lambda v: L + (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo)) * (W - L - 30)  # noqa: E731
    b = []
    ticks = [v for v in (0.2, 0.3, 0.5, 0.7, 1, 1.5, 2, 3, 5, 10, 15) if lo <= v <= hi]
    _grid_x(b, X, ticks, T - 8, T + len(rows) * rowh, fmt=lambda v: f"{v:g}×", zero=1)
    for i, (lab, orr, ci, tip, col) in enumerate(rows):
        y = T + i * rowh + rowh / 2
        b.append(t(L - 12, y + 4, lab, 12.5, "end", INK, 500))
        a, z = max(lo, ci[0]), min(hi, ci[1])
        b.append(f'<line x1="{X(a):.1f}" x2="{X(z):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="3" '
                 f'stroke-linecap="round"/>')
        b.append(dot(X(max(lo, min(hi, orr))), y, col, tip, 5.5))
    if ref_label:
        b.append(t(X(1), 18, ref_label, 11, "middle", MUTED))
    if note:
        b.append(t(L, H - 6, note, 10.5, "start", MUTED))
    return svg(W, H, "".join(b), title, desc)


def sector_or(d):
    h = d["h1"]
    rows = []
    for s, v in sorted(h["odds_ratios_vs_reference"].items(), key=lambda kv: -kv[1]["or"]):
        sig = v["ci95"][1] < 1
        rows.append((s, v["or"], v["ci95"], f"{s}: odds of a correct answer ×{v['or']:.2f} vs "
                     f"{h['reference_sector']} (95% CI {v['ci95'][0]:.2f}–{v['ci95'][1]:.2f})", BAD if sig else MUTED))
    return _forest(rows, "Odds of a correct answer by sector, compared with the easiest sector",
                   f"Logistic regression with a model fixed effect, standard errors clustered by company. Omnibus "
                   f"test of the sector term: χ²({h['df']}) = {h['chi2']:.1f}, p = {h['p']:.2f} (H1 not supported).",
                   lo=0.3, hi=1.5, ref_label=f"1× = {h['reference_sector']}",
                   note=f"Omnibus χ²({h['df']}) = {h['chi2']:.1f}, p = {h['p']:.2f}: H1 not supported. "
                        "Red: interval excludes 1 on its own.")  # fmt: skip


# -- 4 · oil and gas: unit-less items ---------------------------------------------------------------------------


def unitless(d):
    u = d["unitless"]
    secs = sorted(u, key=lambda s: -u[s]["cw_all"])
    W, L, R, T, rowh = 760, 120, 150, 50, 28
    H = T + len(secs) * rowh + 44
    mx = 0.18
    X = lambda v: L + v / mx * (W - L - R)  # noqa: E731
    b = []
    _grid_x(b, X, [0, 0.05, 0.10, 0.15], T - 8, T + len(secs) * rowh, fmt=lambda v: f"{100 * v:.0f}%")
    for i, s in enumerate(secs):
        y = T + i * rowh + rowh / 2
        a, z = u[s]["cw_all"], u[s]["cw_without_unitless"]
        b.append(t(L - 12, y + 4, SHORT[s] if s != "Energy (power and utilities)" else "Utilities", 12.5, "end",
                   INK, 600 if s == "Oil and gas" else 500))
        b.append(f'<line x1="{X(z):.1f}" x2="{X(a):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{AXIS}" stroke-width="2"/>')
        b.append(dot(X(a), y, BAD, f"{s}: confident-wrong {100 * a:.1f}% of answerable, all items", 5))
        b.append(dot(X(z), y, GOOD, f"{s}: {100 * z:.1f}% without items whose unit is stated nowhere", 5))
        b.append(t(W - R + 10, y + 4, f"{100 * u[s]['share_unitless']:.0f}% unit-less", 11, "start", MUTED, cls="num"))
    b.append(legend([(BAD, "All items"), (GOOD, "Without unit-less items")], L, 20))
    dg = d["unitless_cw_digits"]
    share = dg.get("right_digits", 0) / max(1, sum(dg.values()))
    b.append(t(L, H - 6, f"Of the confident-wrong answers on unit-less items, {100 * share:.0f}% have the right digits "
               "with the wrong scale.", 10.5, "start", MUTED))
    return svg(W, H, "".join(b), "Oil and gas: the confident-wrong spike comes from numbers with no unit on the page",
               "Confident-wrong rate by sector (plain setup, 10 main models), with and without items whose unit is "
               "stated nowhere on the pages shown.")


# -- 5 · what makes a datapoint hard (H2-H6) ---------------------------------------------------------------------


def tag_forest(d):
    h = d["h2_h6"]
    lab = {"H2": "H2 · unit stated away from the figure → confident-wrong",
           "H3": "H3 · each extra figure on the line → correct",
           "H4": "H4 · answer is a later figure on the line → correct",
           "H5": "H5 · 10-Q year-to-date vs 3 months → correct",
           "H6": "H6 · word scale: unverifiable-right rather than confident-wrong"}  # fmt: skip
    rows = []
    for k in ("H2", "H3", "H4", "H5", "H6"):
        v = h[k]
        hp = d["holm"]["holm"][k]
        rows.append((lab[k], v["or"], v["ci95"], f"{lab[k]}: odds ×{v['or']:.2f} (95% CI {v['ci95'][0]:.2f}–"
                     f"{v['ci95'][1]:.2f}), Holm p = {hp:.2g}", BAD if v["or"] > 1 and k in ("H2",) else GOOD))
    return _forest(rows, "What makes a datapoint hard: odds ratios for H2–H6",
                   "One logistic regression on all tags with a model fixed effect, standard errors clustered by "
                   "company (plain setup, 10 main models). All five are significant after Holm correction.",
                   lo=0.5, hi=10, W=760, L=410, ref_label="1× = no effect",
                   note="All five Holm p < 0.001.")


# -- 6 · accuracy by figures on the line, position, period --------------------------------------------------------


def tag_rates(d):
    h = d["h2_h6"]
    panels = [("Figures on the line", [(str(k) if k != "6" else "6+", h["H3"]["rates"][k]) for k in
                                       sorted(h["H3"]["rates"], key=int)]),
              ("Answer's position", [("first", h["H4"]["rates"]["first"]), ("later", h["H4"]["rates"]["later"])]),
              ("10-Q period", [("3 months", h["H5"]["rates"]["3_months"]), ("year-to-date", h["H5"]["rates"]["ytd"])])]
    W, H, T, B = 760, 250, 40, 46
    widths = [330, 160, 190]
    b, x0 = [], 30
    Y = lambda v: T + (1 - v) * (H - T - B)  # noqa: E731
    for (title, vals), pw in zip(panels, widths, strict=True):
        b.append(t(x0, 22, title, 12, "start", INK, 600))
        for g in (0.25, 0.5, 0.75):
            b.append(f'<line x1="{x0}" x2="{x0 + pw - 16}" y1="{Y(g):.1f}" y2="{Y(g):.1f}" stroke="{GRID}"/>')
        bw = (pw - 16) / len(vals)
        for i, (lab, r) in enumerate(vals):
            x = x0 + i * bw + 4
            hgt = Y(0) - Y(r)
            b.append(f'<rect x="{x:.1f}" y="{Y(r):.1f}" width="{bw - 8:.1f}" height="{hgt:.1f}" rx="3" fill="{GOOD}">'
                     f"<title>{escape(title)}: {escape(lab)}, accuracy {100 * r:.1f}%</title></rect>")
            b.append(t(x + (bw - 8) / 2, Y(r) - 6, f"{100 * r:.0f}%", 11, "middle", INK2, 600, cls="num"))
            b.append(t(x + (bw - 8) / 2, H - B + 16, lab, 11, "middle", MUTED))
        x0 += pw
    b.append(t(30, H - 6, "Accuracy, plain setup, 10 main models pooled (raw rates; the tests use the regression).", 10.5,
               "start", MUTED))
    return svg(W, H, "".join(b), "Accuracy by where the number sits",
               "Accuracy falls with more figures on the line, for later figures, and for year-to-date periods.")


# -- 7 · H7: retry vs thinking, confident-wrong per 1,000 -----------------------------------------------------------


def h7_arrows(d):
    h7 = d["h7"]["models"]
    models = _order(d, d["main_models"])
    W, L, R, T, rowh = 760, 178, 30, 56, 30
    H = T + len(models) * rowh + 44
    mx = 180
    X = lambda v: L + v / mx * (W - L - R)  # noqa: E731
    b = []
    _grid_x(b, X, [0, 40, 80, 120, 160], T - 8, T + len(models) * rowh)
    for i, m in enumerate(models):
        y = T + i * rowh + rowh / 2
        tt = h7[m]["tests"]
        b.append(t(L - 12, y + 4, NAMES[m], 12.5, "end", INK, 500))
        c2 = tt["C2_confident_wrong"]
        a, z = 1000 * c2["a"] / c2["n"], 1000 * c2["b"] / c2["n"]
        b.append(f'<line x1="{X(a):.1f}" x2="{X(z):.1f}" y1="{y - 5:.1f}" y2="{y - 5:.1f}" stroke="{SETUP["C2"]}" '
                 f'stroke-width="2"/>')
        b.append(dot(X(z), y - 5, SETUP["C2"], f"{NAMES[m]}: check + retry {a:.0f} → {z:.0f} per 1,000 "
                     f"(Holm p = {c2['p_holm']:.2g})", 4))
        b.append(dot(X(a), y - 5, SETUP["C1"], f"{NAMES[m]}: plain {a:.0f} per 1,000 (all questions)", 3.5))
        if "C3_confident_wrong" in tt:
            c3 = tt["C3_confident_wrong"]
            a3, z3 = 1000 * c3["a"] / c3["n"], 1000 * c3["b"] / c3["n"]
            b.append(f'<line x1="{X(a3):.1f}" x2="{X(z3):.1f}" y1="{y + 6:.1f}" y2="{y + 6:.1f}" '
                     f'stroke="{SETUP["C3"]}" stroke-width="2"/>')
            b.append(dot(X(z3), y + 6, SETUP["C3"], f"{NAMES[m]}: thinking {a3:.0f} → {z3:.0f} per 1,000 on the "
                         f"subset (Holm p = {c3['p_holm']:.2g})", 4))
            b.append(dot(X(a3), y + 6, SETUP["C1"], f"{NAMES[m]}: plain {a3:.0f} per 1,000 on the subset", 3.5))
    b.append(legend([(SETUP["C1"], "Plain"), (SETUP["C2"], "Check + retry"), (SETUP["C3"], "Thinking")], L, 22))
    b.append(t(L, H - 6, "Confident-wrong answers per 1,000. Retry: all 10,000 questions; thinking: the 1,000 subset.",
               10.5, "start", MUTED))
    return svg(W, H, "".join(b), "Thinking cuts confident-wrong answers; check + retry adds them (H7)",
               "For each model, confident-wrong per 1,000 answers in the plain setup and after check + retry or "
               "thinking.")


# -- 8 · R1: strict vs pipes ignored ----------------------------------------------------------------------------


def r1_bars(d):
    rb = d["robustness"]
    st, pf = rb["R1"]["models"], rb["R1_pipe_free_exploratory"]["models"]
    models = _order(d, list(st))
    W, L, R, T, rowh, bh = 760, 178, 50, 50, 34, 8
    H = T + len(models) * rowh + 44
    X = lambda v: L + v * (W - L - R)  # noqa: E731
    b = []
    _grid_x(b, X, [0, 0.25, 0.5, 0.75, 1.0], T - 8, T + len(models) * rowh, fmt=lambda v: f"{100 * v:.0f}%")
    for i, m in enumerate(models):
        y = T + i * rowh + 4
        n = st[m]["accuracy"]["n"]
        b.append(t(L - 12, y + 15, _label(m, d), 12.5, "end", INK, 500))
        for j, (v, col, lab) in enumerate([(st[m]["accuracy"]["a"], SETUP["C1"], "Plain C1"),
                                           (st[m]["accuracy"]["b"], R1_STRICT, "R1, strict quote check"),
                                           (pf[m]["accuracy"]["b"], R1_FREE, "R1, pipes ignored")]):
            b.append(hbar(L, y + j * (bh + 1), X(v / n) - L, bh, col, f"{NAMES[m]}, {lab}: {v} of {n} "
                          f"({100 * v / n:.1f}%)"))
    b.append(legend([(SETUP["C1"], "Plain (C1)"), (R1_STRICT, "R1, strict quote check"),
                     (R1_FREE, "R1, pipes ignored (exploratory)")], L, 22))  # fmt: skip
    b.append(t(L, H - 6, "Accuracy on the 1,000-question subset. * supplementary model.", 10.5, "start", MUTED))
    return svg(W, H, "".join(b), "Markdown tables: strict quote checks collapse, reading mostly holds",
               "For each model: accuracy in the plain setup, with Markdown tables under the strict quote check, and "
               "with Markdown tables when the pipes are ignored.")


# -- 9 · ranking under each check ---------------------------------------------------------------------------------


def rank_slope(d):
    rb = d["robustness"]
    ms = d["main_models"]
    cols = [("Plain (C1)", {m: rb["R1"]["models"][m]["accuracy"]["a"] for m in ms}),
            ("R2 prompt", {m: rb["R2"]["models"][m]["accuracy"]["b"] for m in ms}),
            ("R1 strict", {m: rb["R1"]["models"][m]["accuracy"]["b"] for m in ms}),
            ("R1 pipes ignored", {m: rb["R1_pipe_free_exploratory"]["models"][m]["accuracy"]["b"] for m in ms})]
    taus = ["", f"τ = {rb['R2']['kendall_tau_vs_C1']['tau']:.2f}", f"τ = {rb['R1']['kendall_tau_vs_C1']['tau']:.2f}",
            f"τ = {rb['R1_pipe_free_exploratory']['kendall_tau_vs_C1']['tau']:.2f}"]
    W, T, rowh = 760, 62, 28
    H = T + len(ms) * rowh + 20
    xs = [180, 330, 470, 600]
    ranks = [{m: r for r, m in enumerate(sorted(ms, key=lambda m, v=v: -v[m]))} for _, v in cols]
    b = []
    for (name, _), x, tau in zip(cols, xs, taus, strict=True):
        b.append(t(x, 24, name, 12, "middle", INK, 600))
        if tau:
            b.append(t(x, 40, tau + " vs C1", 11, "middle", MUTED))
    for m in ms:
        pts = [(x, T + rk[m] * rowh + rowh / 2) for x, rk in zip(xs, ranks, strict=True)]
        col = GOOD if m in ("qwen3.5-9b", "granite-4.2-8b", "ministral-3-8b") else AXIS
        b.append('<polyline points="' + " ".join(f"{x:.0f},{y:.0f}" for x, y in pts) + f'" fill="none" stroke="{col}" '
                 f'stroke-width="{2.5 if col == GOOD else 1.5}"/>')
        for (x, y), (name, vals) in zip(pts, cols, strict=True):
            b.append(dot(x, y, col if col == GOOD else MUTED, f"{NAMES[m]}, {name}: rank {pts.index((x, y))}", 3.5))
        b.append(t(xs[0] - 12, pts[0][1] + 4, NAMES[m], 12, "end", INK, 500))
        b.append(t(xs[-1] + 12, pts[-1][1] + 4, NAMES[m], 12, "start", INK2))
    return svg(W, H, "".join(b), "Model ranking under a new prompt and under Markdown tables",
               "Ranks by accuracy on the subset. The ranking holds under the alternative prompt and returns when "
               "pipes are ignored; only the strict quote check scrambles it.")


# -- 10 · cost vs accuracy --------------------------------------------------------------------------------------


def cost_scatter(d):
    e = d["energy"]
    ms = [m for m in d["models"] if m in e]
    W, H, L, R, T, B = 760, 400, 70, 160, 40, 56
    xmax = 0.06
    X = lambda v: L + v / xmax * (W - L - R)  # noqa: E731
    Y = lambda v: T + (1 - v) * (H - T - B)  # noqa: E731
    b = []
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        b.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{GRID}"/>')
        b.append(t(L - 8, Y(v) + 4, f"{100 * v:.0f}%", 11, "end", MUTED))
    for v in (0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06):
        b.append(t(X(v), H - B + 18, f"{1000 * v:.0f} Wh", 11, "middle", MUTED))
    tar = d["tariff"]
    placed: list[tuple[float, float]] = []  # label positions, nudged apart vertically
    for m in sorted(ms, key=lambda m: -_acc(d, m)["rate"]):
        a = _acc(d, m)["rate"]
        k = e[m]["kwh_per_1000"]
        tip = (f"{NAMES[m]}: {100 * a:.1f}% accuracy, {1000 * k:.0f} Wh per 1,000 answers "
               f"(₹{k * tar['inr']:.2f}, ${k * tar['usd']:.3f})")
        b.append(dot(X(k), Y(a), GOOD, tip, 5))
        ly = Y(a) + 4
        while any(abs(ly - py) < 13 and abs(X(k) - px) < 110 for px, py in placed):
            ly += 13
        placed.append((X(k), ly))
        if abs(ly - Y(a) - 4) > 1:
            b.append(f'<line x1="{X(k) + 5:.1f}" y1="{Y(a):.1f}" x2="{X(k) + 9:.1f}" y2="{ly - 4:.1f}" stroke="{AXIS}"/>')
        b.append(t(X(k) + 10, ly, NAMES[m], 11, "start", INK2))
    b.append(t(L, 22, "Accuracy (plain setup)", 12, "start", INK, 600))
    b.append(t(W - R, H - 12, "GPU energy per 1,000 answers (RTX 4090 at 450 W)", 12, "end", INK, 600))
    b.append(t(W - R + 10, T + 10, f"at ₹{tar['inr']:.0f}/kWh:", 11, "start", MUTED))
    b.append(t(W - R + 10, T + 26, f"40 Wh = ₹{0.04 * tar['inr']:.2f}", 11, "start", MUTED))
    return svg(W, H, "".join(b), "Accuracy against energy per 1,000 answers",
               "Each dot is a model: plain-setup accuracy against measured GPU energy per 1,000 answers.")


# -- 11 · 4-bit vs full precision -------------------------------------------------------------------------------


def quant_pairs(d):
    qz = d["robustness"]["quantisation_17_3"]
    W, L, R, T, rowh = 760, 178, 40, 76, 40
    H = T + len(qz) * rowh + 44
    pw = (W - L - R - 40) / 2
    b = []
    for p, (key, title, mx) in enumerate([("accuracy", "Correct (of 900)", 900), ("confident_wrong",
                                                                                "Confident-wrong (of 1,000)", 100)]):
        x0 = L + p * (pw + 40)
        X = lambda v, x0=x0, mx=mx: x0 + v / mx * pw  # noqa: E731
        b.append(t(x0, 56, title, 12, "start", INK, 600))
        for v in ([0, 300, 600, 900] if mx == 900 else [0, 25, 50, 75, 100]):
            b.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T - 6}" y2="{T + len(qz) * rowh}" stroke="{GRID}"/>')
            b.append(t(X(v), T + len(qz) * rowh + 16, str(v), 11, "middle", MUTED))
        for i, (q4, v) in enumerate(qz.items()):
            y = T + i * rowh + rowh / 2
            if p == 0:
                b.append(t(L - 12, y + 4, NAMES[v["full_precision"]], 12.5, "end", INK, 500))
            r = v[key]
            sig = r["p_holm"] < 0.05
            b.append(f'<line x1="{X(r["a"]):.1f}" x2="{X(r["b"]):.1f}" y1="{y}" y2="{y}" stroke="{AXIS}" '
                     f'stroke-width="2"/>')
            b.append(dot(X(r["a"]), y, SETUP["C2"], f"{NAMES[v['full_precision']]}, full precision: {r['a']}", 5))
            col = BAD if sig else MUTED
            b.append(dot(X(r["b"]), y, col, f"{NAMES[q4]}: {r['b']} (Holm p = {r['p_holm']:.2g})", 5))
            b.append(t(X(max(r["a"], r["b"])) + 12, y + 4, f"{r['a']} → {r['b']}", 11, "start", INK2, cls="num"))
    b.append(legend([(SETUP["C2"], "Full precision"), (BAD, "4-bit, significant"), (MUTED, "4-bit, not significant")],
                    L, 16))
    return svg(W, H, "".join(b), "4-bit builds: a small accuracy cost, no significant rise in confident-wrong",
               "Plain setup on the 1,000-question subset: full precision vs the 4-bit build of the same model.")


ALL = {"timeline": timeline, "sector_heatmap": sector_heatmap, "sector_or": sector_or, "unitless": unitless,
       "tag_forest": tag_forest, "tag_rates": tag_rates, "h7_arrows": h7_arrows, "r1_bars": r1_bars,
       "rank_slope": rank_slope, "cost_scatter": cost_scatter, "quant_pairs": quant_pairs}  # fmt: skip
