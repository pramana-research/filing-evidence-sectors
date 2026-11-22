"""Build the Sectors research pages for pramana-research.com from report/build/data.json.

    uv run --extra analysis python report/data.py                      # the numbers
    uv run --extra report python report/build.py --out ../pramana-research-landing   # research/filing-evidence-sectors/**

Every number in the prose comes from data.json through headline(); the words are in report/templates/.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import charts  # noqa: E402

VERSION = "1.0"
DATE = "23 November 2026"
SITE = "https://pramana-research.com"
PATH = "/research/filing-evidence-sectors"
GITHUB = "https://github.com/pramana-research/filing-evidence-sectors"
HF = "https://huggingface.co/datasets/pramana-research/filing-evidence-sectors"
V1 = "/research/filing-evidence"
V1_ARXIV = "https://arxiv.org/abs/2611.24990"
TITLE = "Units, Columns and Periods: Presentation, Not Sector, Drives Errors When Small Open Models Read SEC Filings"
SUBTITLE = "Filing-Evidence Sectors: a pre-registered follow-up across ten sectors, 10,000 questions and eleven open models"


def pct(r, nd=1):
    return f"{100 * r:.{nd}f}%"


def headline(d: dict) -> dict:
    """The figures the prose quotes, computed once so the text and the charts can't disagree."""
    T, main = d["sectors_table"], d["main_models"]
    acc = {m: T[m]["C1"]["all"]["accuracy"]["rate"] for m in d["models"]}
    cw = {m: T[m]["C1"]["all"]["confident_wrong"]["rate"] for m in d["models"]}
    by_acc = sorted(main, key=lambda m: -acc[m])
    pooled = {}
    for s in d["sectors"]:
        k = sum(T[m]["C1"][s]["accuracy"]["k"] for m in main)
        n = sum(T[m]["C1"][s]["accuracy"]["n"] for m in main)
        kc = sum(T[m]["C1"][s]["confident_wrong"]["k"] for m in main)
        nc = sum(T[m]["C1"][s]["confident_wrong"]["n"] for m in main)
        pooled[s] = {"acc": k / n, "cw": kc / nc}
    sec_sorted = sorted(pooled, key=lambda s: -pooled[s]["acc"])
    h7m = d["h7"]["models"]
    c3 = [m for m in main if "C3_confident_wrong" in h7m[m]["tests"]]
    rb = d["robustness"]
    r3 = rb["R3"]["models"]
    e = d["energy"]
    wh = {m: 1000 * e[m]["kwh_per_1000"] for m in d["models"] if m in e}
    q = rb["quantisation_17_3"]
    u = d["unitless"]["Oil and gas"]
    dg = d["unitless_cw_digits"]
    pf = rb["R1_pipe_free_exploratory"]["models"]
    st = rb["R1"]["models"]
    return {
        "acc": acc, "cw": cw, "by_acc": by_acc, "best": by_acc[0], "worst": by_acc[-1],
        "acc_top": acc[by_acc[0]], "acc_bottom": acc[by_acc[-1]],
        "pooled": pooled, "sec_sorted": sec_sorted, "sec_best": sec_sorted[0], "sec_worst": sec_sorted[-1],
        "sec_cw_max": max(pooled, key=lambda s: pooled[s]["cw"]), "sec_cw_min": min(pooled, key=lambda s: pooled[s]["cw"]),
        "og": u, "og_digits": dg.get("right_digits", 0) / max(1, sum(dg.values())),
        "c3_models": c3, "c3_lower": [m for m in c3 if h7m[m]["verdict"]["C3_lowers_cw"]],
        "c2_raises": [m for m in main if h7m[m]["verdict"]["C2_raises_cw"]],
        "c2_acc_up": [m for m in main if h7m[m]["tests"]["C2_accuracy"]["b"] > h7m[m]["tests"]["C2_accuracy"]["a"]
                      and h7m[m]["tests"]["C2_accuracy"]["p_holm"] < 0.05],
        "pooled_c3": d["h7"]["pooled_C3_confident_wrong"],
        "r3_min": min(v["outcome_changed"]["rate"] for v in r3.values()),
        "r3_max": max(v["outcome_changed"]["rate"] for v in r3.values()),
        "tau_r2": rb["R2"]["kendall_tau_vs_C1"]["tau"], "tau_r1": rb["R1"]["kendall_tau_vs_C1"]["tau"],
        "tau_pf": rb["R1_pipe_free_exploratory"]["kendall_tau_vs_C1"]["tau"],
        "h8": rb["H8"], "r1_cw_down": [m for m in main if pf[m]["confident_wrong"]["b"] < pf[m]["confident_wrong"]["a"]],
        "r1_worst_strict": min(main, key=lambda m: st[m]["accuracy"]["b"] / st[m]["accuracy"]["a"]),
        "r1_pf_max_loss_model": max(main, key=lambda m: (pf[m]["accuracy"]["a"] - pf[m]["accuracy"]["b"]) / pf[m]["accuracy"]["n"]),
        "r1_pf_max_loss": max(100 * (pf[m]["accuracy"]["a"] - pf[m]["accuracy"]["b"]) / pf[m]["accuracy"]["n"] for m in main),
        "wh": wh, "wh_min": min(wh, key=wh.get), "wh_max": max(wh, key=wh.get),
        "q": q, "cross": d["energy_cross_check"],
    }  # fmt: skip


def update_site(site: Path, d: dict, H: dict) -> None:
    """Add (or refresh) this study's card on /research and its URLs in sitemap.xml; idempotent."""
    idx = site / "research" / "index.html"
    html = idx.read_text()
    start, end = "<!-- filing-evidence-sectors card -->", "<!-- /filing-evidence-sectors card -->"
    card = (f'''{start}
<a class="card" href="{PATH}" style="padding:28px;max-width:900px;margin-bottom:20px">
  <p class="eyebrow" style="margin-bottom:12px">Community research report · Not peer-reviewed · {DATE} · Krishna Nandula</p>
  <div class="n" style="font-size:24px;line-height:1.25">{TITLE}</div>
  <p style="color:#3D4452;margin:14px 0 0;font-size:16px">A pre-registered follow-up to Filing-Evidence: 10,000 questions across ten sectors, eleven open models. Which industry a number comes from hardly matters; how it is printed does. Units stated away from the figure, crowded lines, later columns and year-to-date periods drive the errors.</p>
  <div class="r" style="margin-top:18px"><span>Read the paper →</span><span>PDF · code · data</span></div>
</a>
{end}''')
    if start in html:
        html = html[: html.index(start)] + card + html[html.index(end) + len(end):]
    else:
        anchor = '<a class="card" href="/research/filing-evidence"'
        html = html.replace(anchor, card + "\n" + anchor, 1)
    idx.write_text(html)
    sm = site / "sitemap.xml"
    xml = sm.read_text()
    day = "2026-11-23"
    urls = [f"{SITE}{PATH}", f"{SITE}{PATH}/pdf/filing-evidence-sectors.pdf"] + [
        f"{SITE}{PATH}/{m.replace('.', '-')}" for m in d["models"]] + [
        f"{SITE}{PATH}/pdf/{m.replace('.', '-')}.pdf" for m in d["models"]]
    lines = [ln for ln in xml.splitlines() if f"{PATH}<" not in ln and f"{PATH}/" not in ln]
    close = lines.index("</urlset>")
    lines[close:close] = [f"  <url><loc>{u}</loc><lastmod>{day}</lastmod></url>" for u in urls]
    sm.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="checkout of the site repository")
    args = ap.parse_args()
    d = json.loads((HERE / "build" / "data.json").read_text())
    H = headline(d)
    env = Environment(loader=FileSystemLoader(HERE / "templates"), undefined=StrictUndefined, autoescape=False)
    env.filters.update({
        "pct": pct, "pct0": lambda r: pct(r, 0), "name": lambda m: charts.NAMES[m], "slug": lambda m: m.replace(".", "-"),
        "short": lambda s: charts.SHORT[s], "num": lambda n: f"{n:,}", "f2": lambda x: f"{x:.2f}",
        "p": lambda p: "< 0.001" if p < 0.001 else f"{p:.3f}" if p < 0.01 else f"{p:.2f}",
    })  # fmt: skip
    figs = {k: fn(d) for k, fn in charts.ALL.items()}
    common = {"d": d, "H": H, "F": figs, "SITE": SITE, "PATH": PATH, "GITHUB": GITHUB, "HF": HF, "V1": V1,
              "V1_ARXIV": V1_ARXIV, "TITLE": TITLE, "SUBTITLE": SUBTITLE, "VERSION": VERSION, "DATE": DATE,
              "NAMES": charts.NAMES}  # fmt: skip
    out = Path(args.out) / PATH.lstrip("/")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "index.html").write_text(env.get_template("paper.html.j2").render(path=PATH, **common))
    for m in d["models"]:
        page = out / m.replace(".", "-")
        page.mkdir()
        (page / "index.html").write_text(env.get_template("model.html.j2").render(
            path=f"{PATH}/{m.replace('.', '-')}", m=m, **common))  # fmt: skip
    update_site(Path(args.out), d, H)
    print(f"wrote {out}: paper + {len(d['models'])} model pages; research index and sitemap updated")


if __name__ == "__main__":
    main()
