"""All charts on one page for review: report/build/charts.html."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import charts  # noqa: E402

d = json.loads((HERE / "build" / "data.json").read_text())
parts = []
for name, fn in charts.ALL.items():
    try:
        parts.append(f"<section><h2>{name}</h2>{fn(d)}</section>")
    except Exception as e:  # show the failure in the preview instead of stopping
        parts.append(f"<section><h2>{name}</h2><pre>{type(e).__name__}: {e}</pre></section>")
        print(f"{name}: {type(e).__name__}: {e}", file=sys.stderr)
css = ("body{background:#FAFAF7;font-family:Inter,system-ui,sans-serif;max-width:800px;margin:24px auto;padding:0 16px}"
       "svg{width:100%;height:auto;display:block}h2{font:600 13px monospace;color:#5B6472;margin:28px 0 6px}"
       ".num{font-variant-numeric:tabular-nums}")
(HERE / "build" / "charts.html").write_text(f"<!doctype html><meta charset=utf-8><style>{css}</style>" + "".join(parts))
print("report/build/charts.html")
