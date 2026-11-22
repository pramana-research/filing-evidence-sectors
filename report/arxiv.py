"""The arXiv version of the Sectors paper: LaTeX source, vector figures, and the upload bundle.

    uv run --extra analysis --extra report python report/arxiv.py            # -> paper/main.tex, paper/figures/*.pdf
    cd paper && latexmk -pdf main.tex                                       # no BibTeX: references are inline
    uv run --extra analysis --extra report python report/arxiv.py --bundle   # -> paper/arxiv-source.tar.gz

Every number comes from report/build/data.json through build.headline(), as on the website; the text is in
report/latex/main.tex.j2. Figures are the website's SVG charts, printed to tightly cropped vector PDFs by headless
Chrome (fonts embedded). Helpers copied from Filing-Evidence v1's report/arxiv.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402
import charts  # noqa: E402

PAPER = ROOT / "paper"
FONTS = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&"
         "family=JetBrains+Mono:wght@400;500&display=swap")


def chrome() -> str:
    for c in ("google-chrome", "chromium", "chromium-browser"):
        if p := shutil.which(c):
            return p
    sys.exit("headless Chrome is needed to print the figures")


def svg_to_pdf(svg: str, out: Path) -> None:
    """One SVG -> one PDF page of exactly the SVG's size (vector, fonts embedded)."""
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    w, h = float(m.group(1)), float(m.group(2))
    svg = svg.replace("<svg ", f'<svg width="{w}" height="{h}" ', 1)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><link href="{FONTS}" rel="stylesheet">
<style>@page {{ size: {w}px {h}px; margin: 0 }} html, body {{ margin: 0; background: #fff }}
svg {{ display: block; font-family: Inter, sans-serif }} svg .num {{ font-family: 'JetBrains Mono', monospace }}
</style></head><body>{svg}</body></html>"""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "fig.html"
        src.write_text(html)
        subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--virtual-time-budget=6000", f"--print-to-pdf={out}", src.as_uri()],
                       check=True, capture_output=True)


def tex_escape(s) -> str:
    """Plain text -> LaTeX (for question wording, quoted lines, model names)."""
    s = str(s)
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
           "“": "``", "”": "''", "’": "'", "‘": "`", "–": "--", "—": "---", "…": r"\ldots{}",
           "≠": r"$\neq$", "→": r"$\rightarrow$", "×": r"$\times$", "§": r"\S{}", "✓": r"\checkmark{}"}
    return "".join(rep.get(c, c) for c in s)


def render() -> None:
    d = json.loads((HERE / "build" / "data.json").read_text())
    H = build.headline(d)
    (PAPER / "figures").mkdir(parents=True, exist_ok=True)
    for name, fn in charts.ALL.items():
        svg_to_pdf(fn(d), PAPER / "figures" / f"{name}.pdf")
    env = Environment(loader=FileSystemLoader(HERE / "latex"), undefined=StrictUndefined,
                      block_start_string="<%", block_end_string="%>", variable_start_string="<<",
                      variable_end_string=">>", comment_start_string="<#", comment_end_string="#>",
                      trim_blocks=True, lstrip_blocks=True, autoescape=False)
    env.filters.update(
        e=tex_escape, name=lambda m: tex_escape(charts.NAMES[m]), short=lambda s: tex_escape(charts.SHORT[s]),
        pct=lambda r, nd=1: f"{100 * r:.{nd}f}\\%", thou=lambda n: f"{n:,}".replace(",", "{,}"),
        num=lambda x, nd=1: f"{x:.{nd}f}", p=lambda p: "<0.001" if p < 0.001 else f"{p:.3f}" if p < 0.01 else f"{p:.2f}",
    )
    tex = env.get_template("main.tex.j2").render(
        d=d, H=H, VERSION=build.VERSION, GITHUB=build.GITHUB, HF=build.HF, TITLE=build.TITLE,
        AUTHOR_EMAIL=os.environ.get("PAPER_AUTHOR_EMAIL", ""),
    )
    (PAPER / "main.tex").write_text(tex)
    for f in (PAPER / "figures").glob("*.pdf"):  # keep only the figures the paper uses
        if f"{{{f.name}}}" not in tex:
            f.unlink()
    print(f"wrote {PAPER / 'main.tex'} and {len(charts.ALL)} figures")


def bundle() -> None:
    """The upload for arXiv: main.tex and the figures (references are inline, so no .bbl is needed)."""
    out = PAPER / "arxiv-source.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(PAPER / "main.tex", arcname="main.tex")
        for f in sorted((PAPER / "figures").glob("*.pdf")):
            tar.add(f, arcname=f"figures/{f.name}")
    print(f"wrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", action="store_true", help="only pack paper/ into arxiv-source.tar.gz")
    a = ap.parse_args()
    bundle() if a.bundle else render()
