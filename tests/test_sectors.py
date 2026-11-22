"""Guards for Filing-Evidence Sectors: the dataset matches its frozen fingerprint, and the build's own rules (v1
exclusion key, difficulty tags) behave as PROTOCOL.md §4.4 and §6 say."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v1"))
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import build as sectors  # noqa: E402
import freeze  # noqa: E402

HAVE_DATA = (ROOT / "dataset" / "questions.jsonl").exists()
HAVE_V1 = sectors.V1_QUESTIONS.exists()


@pytest.mark.skipif(not HAVE_DATA, reason="run `python hf_data.py pull` first")
def test_dataset_matches_its_frozen_fingerprint():
    frozen = json.loads((ROOT / "dataset" / "FROZEN.json").read_text())["fingerprint"]
    assert freeze.fingerprint() == frozen


def test_v1_exclusion_key_matches_the_builder_candidate_key():
    # builder.candidates: f"{accession}:{concept}:{start}:{end}:{instant}:{sorted(dims.items())}"
    gold = {
        "concept": "us-gaap:Goodwill",
        "period": {"start": None, "end": None, "instant": "2025-12-27"},
        "dims": {"us-gaap:StatementBusinessSegmentsAxis": "pep:AsiaPacificFoodsSegmentMember"},
    }
    expected = (
        "0000077476-26-000007:us-gaap:Goodwill:None:None:2025-12-27:"
        "[('us-gaap:StatementBusinessSegmentsAxis', 'pep:AsiaPacificFoodsSegmentMember')]"
    )
    assert sectors.fact_key("0000077476-26-000007", gold) == expected


@pytest.mark.skipif(not HAVE_V1, reason="run `python hf_data.py pull` first (fetches v1's questions)")
def test_v1_exclusions_cover_every_v1_question_text():
    keys, texts = sectors.v1_exclusions()
    assert len(texts) == 1000
    assert len(keys) == 875  # the answerable questions


def test_figures_after_label_and_position():
    line = "Balance as of December 27, 2025 $ 1,422 $ 12,125 $ 1,921 $ 2,688 $ 385 $ 375 $ 18,916"
    figs = sectors.figures_after_label(line)
    assert len(figs) == 7
    assert [sectors.digits(f) for f in figs].index("375") == 5


def test_period_length_buckets():
    assert sectors.period_length({"instant": "2026-06-30"}) == "instant"
    assert sectors.period_length({"start": "2026-07-01", "end": "2026-09-30"}) == "3 months"
    assert sectors.period_length({"start": "2026-01-01", "end": "2026-09-30"}) == "9 months"
    assert sectors.period_length({"start": "2025-01-01", "end": "2025-12-31"}) == "12 months"


def test_units_location():
    gold_usd = {"unit": "USD", "scale": 6}
    page = "CONSOLIDATED BALANCE SHEETS\n(In millions)\nTotal liabilities 275,746 285,508"
    assert sectors.units_location(page, "Total liabilities 275,746 285,508", gold_usd) == "page header"
    table = "\n".join(["Note 4", "Goodwill"] * 6 + ["(in thousands)", "Balance 1,422 12,125"])
    assert sectors.units_location(table, "Balance 1,422 12,125", gold_usd) == "table or column header"
    prose = "Revenue of $12.6 billion was recognized in the period."
    assert sectors.units_location(prose, prose, {"unit": "USD", "scale": 9}) == "in the line"
    eps = {"unit": "USD per share", "scale": 0}
    assert sectors.units_location("x", "Diluted earnings per share $ 2.72 $ 2.10", eps) == "in the row label"
