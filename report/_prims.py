from __future__ import annotations

import math
from html import escape

OUT = {"correct": "#2E3F9E", "unverifiable_right": "#8592D6", "missed": "#D9D6CE", "caught_wrong": "#E57C62",
       "confident_wrong": "#B3302A", "invalid": "#A7A398"}
OUT_ORDER = ["correct", "unverifiable_right", "missed", "invalid", "caught_wrong", "confident_wrong"]
SETUP = {"C1": "#8F9BDD", "C2": "#5466C4", "C3": "#1F2C73"}
SETUP_NAME = {"C1": "Plain", "C2": "Check + retry", "C3": "Thinking"}
INK, INK2, MUTED, GRID, AXIS, SURF = "#12161C", "#3D4452", "#5B6472", "#E7E8E3", "#C3C8D2", "#FAFAF7"
GOOD, BAD = "#2E3F9E", "#B3302A"

NAMES = {
    "qwen3.5-9b": "Qwen3.5-9B", "granite-4.2-8b": "Granite-4.2-8B", "ministral-3-8b": "Ministral-3-8B",
    "olmo-3-7b": "OLMo-3-7B", "nemotron-nano-9b-v2": "Nemotron-Nano-9B-v2", "gpt-oss-20b": "gpt-oss-20b",
    "phi-4": "Phi-4", "gemma-3-12b": "Gemma-3-12B", "glm-4.6v-flash": "GLM-4.6V-Flash",
    "llama-3.1-8b": "Llama-3.1-8B", "qwen3-8b": "Qwen3-8B",
}


def slug(m: str) -> str:
    return m.replace(".", "-")


def t(x, y, s, size=12, anchor="start", fill=INK2, weight=400, cls="", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" '
            f'font-weight="{weight}" class="{cls}" {extra}>{escape(str(s))}</text>')


def svg(w, h, body, title, desc, cls="chart"):
    return (f'<svg class="{cls}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d" '
            f'xmlns="http://www.w3.org/2000/svg"><title>{escape(title)}</title><desc>{escape(desc)}</desc>'
            f"{body}</svg>")


def hbar(x, y, w, h, fill, tip, round_end=True):
    """Horizontal bar from the baseline x; 4px rounded data end, square at the baseline."""
    if w <= 0:
        return ""
    r = min(4, h / 2, w) if round_end else 0
    path = (f"M{x:.1f},{y:.1f} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r:.1f} a{r},{r} 0 0 1 -{r},{r} "
            f"h-{w - r:.1f} z") if r else f"M{x:.1f},{y:.1f} h{w:.1f} v{h:.1f} h-{w:.1f} z"
    return f'<path d="{path}" fill="{fill}"><title>{escape(tip)}</title></path>'


def dot(x, y, fill, tip, r=5):
    return (f'<g class="mark"><circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 2}" fill="{SURF}"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"><title>{escape(tip)}</title></circle>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 7}" fill="transparent"><title>{escape(tip)}</title>'
            "</circle></g>")


def legend(items, x, y, gap=22):
    out, cx = [], x
    for color, label in items:
        out.append(f'<rect x="{cx:.1f}" y="{y - 9:.1f}" width="10" height="10" rx="2" fill="{color}"/>')
        out.append(t(cx + 15, y, label, 12, fill=INK2))
        cx += 15 + 6.6 * len(label) + gap
    return "".join(out)


def pct(r):
    return f"{100 * r:.1f}%"


