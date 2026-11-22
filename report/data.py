"""Every number the Sectors report quotes, in one dict (charts and prose read only this).

    uv run --extra analysis python report/data.py      # writes report/build/data.json

Reads the analysis outputs (results/analysis/*.json, from analyze.py), the stored answers and run records, and the
GPU energy log (results/energy/gpu-energy.csv; PROTOCOL §14, Deviation 7).
"""

from __future__ import annotations

import csv
import json
import statistics
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import analyze as A  # noqa: E402

AN = ROOT / "results" / "analysis"
OUT = Path(__file__).parent / "build"
TARIFF_INR, TARIFF_USD = 8.0, 0.17  # per kWh: ₹8 (the user's home tariff), US$0.17 (US residential average, 2026)
QUANT = A.QUANT


def j(name: str) -> dict:
    return json.loads((AN / name).read_text())


def run_meta(m: str, s: str) -> dict:
    return json.loads((ROOT / "results" / m / s / "run.json").read_text())


def energy_rows() -> list[tuple[int, str, float]]:
    with (ROOT / "results" / "energy" / "gpu-energy.csv").open() as fh:
        return [(int(r["t"]), r["boot_id"], float(r["gpu_kwh"])) for r in csv.DictReader(fh)]


def run_energy(meta: dict, rows) -> dict | None:
    """kWh over a run from the cumulative counter: readings nearest the start and end, same boot, within 60 s."""
    a = datetime.fromisoformat(meta["started"]).timestamp()
    b = datetime.fromisoformat(meta["finished"]).timestamp()
    ra = min(rows, key=lambda r: abs(r[0] - a))
    rb = min(rows, key=lambda r: abs(r[0] - b))
    if ra[1] != rb[1] or abs(ra[0] - a) > 60 or abs(rb[0] - b) > 60:
        return None
    kwh = rb[2] - ra[2]
    return {"kwh": kwh, "minutes": (b - a) / 60, "mean_w": kwh * 3.6e6 / max(1, rb[0] - ra[0])}


def speed(m: str, s: str) -> dict:
    rows = list(A.load_answers(m, s).values())
    secs = sorted(r["seconds"] for r in rows)
    toks = [r["completion_tokens"] for r in rows if r.get("completion_tokens") is not None]
    meta = run_meta(m, s)
    mins = (datetime.fromisoformat(meta["finished"]) - datetime.fromisoformat(meta["started"])).total_seconds() / 60
    return {"median_s": statistics.median(secs), "p95_s": secs[int(0.95 * (len(secs) - 1))],
            "out_tokens_mean": statistics.mean(toks) if toks else None, "answers_per_hour": len(rows) / mins * 60,
            "n": len(rows)}  # fmt: skip


def commit_time(rev: str, repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%cI", rev], capture_output=True,
                          text=True, check=True).stdout.strip()  # fmt: skip


def main() -> None:
    qs = A.load_questions()
    ms_all = A.models()
    main_ms = [m for m in ms_all if m not in A.SUPPLEMENTARY]
    sectors = sorted({q["sector"] for q in qs.values()})
    secj, h1, hh, h7, rb, holm = (j(f) for f in ("sectors.json", "h1.json", "h2_h6.json", "h7.json",
                                                   "robustness.json", "holm.json"))  # fmt: skip

    # the oil-and-gas question: confident-wrong by sector, with and without the items whose unit is stated nowhere
    df = A.tag_frame(qs, main_ms)
    unitless = {
        s: {"cw_all": float(g["cw"].mean()), "cw_without_unitless": float(g[g["units"] != "none"]["cw"].mean()),
            "share_unitless": float((g["units"] == "none").mean()),
            "cw_unitless": float(g[g["units"] == "none"]["cw"].mean()) if (g["units"] == "none").any() else None}
        for s, g in df.groupby("sector")
    }  # fmt: skip
    # among confident-wrong answers on unit-less items: right digits, wrong scale?
    digits = Counter()
    for m in main_ms:
        for i, a in A.load_answers(m, "C1").items():
            q = qs[i]
            if (q.get("tags") or {}).get("units_location") == "none" and a["outcome"] == "confident_wrong":
                digits["right_digits" if a.get("right_ignoring_scale") else "other"] += 1

    rows = energy_rows()
    energy = {}
    for m in ms_all + list(QUANT):
        s = "C1" if m in QUANT else "R2"
        e = run_energy(run_meta(m, s), rows)
        if e:
            energy[m] = {**e, "run": s, "kwh_per_1000": e["kwh"] * 1000 / 1000,
                         "inr_per_1000": e["kwh"] * TARIFF_INR, "usd_per_1000": e["kwh"] * TARIFF_USD}  # fmt: skip
    cross = {}
    for m in A.R3_MODELS:
        e = run_energy(run_meta(m, "R3"), rows)
        if e:
            cross[m] = {"R3_kwh": e["kwh"], "R2_kwh": energy.get(m, {}).get("kwh")}

    fe = Path.home() / "filing-evidence"
    timeline = {
        "protocol": commit_time("00260c4", fe), "freeze": commit_time("4f2ce0c", fe),
        "runs_start": "2026-11-21T14:05:00+05:30", "main_runs_done": "2026-11-22T16:27:37+05:30",
        "robustness_fixed": commit_time("1ca2eed", ROOT), "robustness_done": "2026-11-22T22:02:19+05:30",
    }  # fmt: skip

    subset = json.loads((ROOT / "dataset" / "subsets.json").read_text())["c3_and_robustness"]
    truncated = {m: sum(bool(a.get("truncated")) for a in A.load_answers(m, "C3").values())
                 for m in ms_all if A.load_answers(m, "C3")}
    r1f = json.loads((ROOT / "dataset" / "r1" / "FROZEN.json").read_text())["tables"]
    cross_diff = max(abs(v["R3_kwh"] - v["R2_kwh"]) / v["R3_kwh"] for v in cross.values() if v["R2_kwh"])
    d = {
        "models": ms_all, "main_models": main_ms, "supplementary": sorted(A.SUPPLEMENTARY), "sectors": sectors,
        "n_questions": len(qs), "n_answerable": sum(q["gold"]["status"] == "found" for q in qs.values()),
        "n_companies": len({q["ticker"] for q in qs.values()}), "n_filings": len({q["accession"] for q in qs.values()}),
        "subset": len(subset),
        "answers_core": sum(len(A.load_answers(m, s)) for m in ms_all for s in ("C1", "C2", "C3", "R1", "R2", "R3")),
        "answers_total": sum(len(A.load_answers(m, s)) for m in ms_all + list(QUANT)
                             for s in ("C1", "C2", "C3", "R1", "R2", "R3")),
        "sectors_table": secj, "h1": h1, "h2_h6": hh, "h7": h7, "robustness": rb, "holm": holm,
        "c3_truncated": truncated, "r1_header_aligned": r1f["header_aligned"] / r1f["tables_with_header"],
        "energy_cross_max_diff": cross_diff,
        "unitless": unitless, "unitless_cw_digits": dict(digits), "energy": energy, "energy_cross_check": cross,
        "speed": {m: {s: speed(m, s) for s in ("C1", "C3") if A.load_answers(m, s)} for m in ms_all},
        "tariff": {"inr": TARIFF_INR, "usd": TARIFF_USD}, "timeline": timeline,
        "tags": {k: dict(Counter(str((q.get("tags") or {}).get(k)) for q in qs.values()))
                 for k in ("units_location", "figures_on_line", "value_position", "period_length", "word_scale")},
    }  # fmt: skip
    OUT.mkdir(exist_ok=True)
    (OUT / "data.json").write_text(json.dumps(d, indent=1, default=str))
    print(f"report/build/data.json: {len(d['models'])} models, {d['answers_total']:,} answers, "
          f"energy for {len(energy)} runs")


if __name__ == "__main__":
    main()
