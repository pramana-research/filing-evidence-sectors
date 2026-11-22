# v1/: frozen copies of Filing-Evidence v1 modules

Unchanged copies of the modules this study reuses from Filing-Evidence v1
([github.com/pramana-research/filing-evidence](https://github.com/pramana-research/filing-evidence), commit
`a08e135`), so the study runs on its own. PROTOCOL §0 requires the same page rendering, answer key, wording rules
and checker as v1, so these files are not edited here.

| File | What |
|---|---|
| `ixbrl.py` | reads inline-XBRL filings into pages and tagged facts |
| `builder.py` | answerability, wording, slices, shown pages, gold answers (v1 §5) |
| `checker.py` | the automatic checks, outcomes, error categories and metrics (v1 §7–§9) |
| `edgar.py`, `fetch.py` | SEC EDGAR client and downloader |
| `paths.py` | where the filings live (`DATA_DIR`); the only change: `.env` and the default `data/` resolve to the repo root |

`v1/dataset/questions.jsonl` (not in git) holds v1's questions, fetched by `python hf_data.py pull`; the build
uses them only to exclude every v1 datapoint (PROTOCOL §4.4).
