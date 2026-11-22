---
pretty_name: Filing-Evidence Sectors
license: cc-by-4.0
language: [en]
task_categories: [question-answering]
tags: [finance, sec-filings, xbrl, evidence, benchmark]
size_categories: [10K<n<100K]
configs:
  - config_name: questions
    data_files: dataset/questions.jsonl
  - config_name: pages
    data_files: dataset/pages.jsonl
---

# Filing-Evidence Sectors (data)

The data half of Filing-Evidence Sectors. Code, protocol, analysis and run records:
[github.com/pramana-research/filing-evidence-sectors](https://github.com/pramana-research/filing-evidence-sectors).

| Path | What |
|---|---|
| `dataset/questions.jsonl` | 10,000 questions (1,000 per sector): slice, wording, the pages shown, gold answer (value, scale, unit, period, evidence page and line), difficulty tags |
| `dataset/pages.jsonl` | the text of every page shown, keyed by page id |
| `results/<model>/<setup>/answers.jsonl` | for each model and setup: every request, raw reply (and reasoning), parsed answer, failed check, outcome |
| `logs/sectors-serve-<model>.log` | the vLLM server log of each model's runs |

The questions and pages are frozen: their fingerprint is
`9a007d8046167c38d67d8570435ccd95f4dd7effc43bb3fc06ce4a64fe75346c`, recorded in git (`dataset/FROZEN.json`) before
any model ran. `python hf_data.py pull` in the code repo downloads this dataset and verifies it.

Source: SEC EDGAR filings (public records): the most recent 10-K and 10-Q of 100 US companies, ten in each of ten
sectors. No datapoint from Filing-Evidence v1 is reused.

Licence: CC BY 4.0, Copyright 2026 Pramana Research. Model outputs remain subject to the licence of the model that
produced them.

## Disclaimer

This is an independent community research project, carried out in a personal capacity; it does not represent the views of any employer or other organisation. It is not affiliated with, sponsored or endorsed by any company or model developer named here; all names and trademarks belong to their owners. Results describe specific model versions under one fixed setup and are not a general judgement of any model. The data, results and code are provided as is, without warranty, and may contain errors; check any figure against the original filing. Nothing here is financial, investment or legal advice.
