# Filing-Evidence Sectors

Can small open models pull a number out of an SEC filing **with evidence a machine can check** (the page and the
verbatim line), across ten industry sectors? And which datapoints make them fail?

10,000 questions (1,000 per sector) over 200 recent 10-K / 10-Q filings of 100 US companies in ten sectors, with
gold answers taken from the filings' own inline XBRL tags and difficulty tags on every question. Eleven open
models, each run on one RTX 4090 with vLLM, in three setups: plain (C1), check + retry (C2) and thinking (C3, on a
1,000-question subset). Everything was pre-registered in [PROTOCOL.md](PROTOCOL.md) before any question was built
or any model was run; later changes are logged in its §14.

This study extends [Filing-Evidence v1](https://github.com/pramana-research/filing-evidence) with the same method
(page rendering, answer key, prompt, setups, checker), so the results can be compared directly. v1 is not changed.

**Code and record here, data on Hugging Face.** Questions, page texts, every model reply (with reasoning) and the
server logs are in the Hugging Face dataset
[`pramana-research/filing-evidence-sectors`](https://huggingface.co/datasets/pramana-research/filing-evidence-sectors).
Git holds the code, the protocol, the dataset fingerprint (`dataset/FROZEN.json`), each run's `summary.json` /
`run.json`, the run logs and the analysis.

## Pre-registration record

This repository was split out of the Filing-Evidence repository on 2026-11-22 (PROTOCOL §14, deviation 4), keeping
the study's commit history with its original dates. The public, timestamped record of the pre-registration is in
the original repository:

| Step | Commit in `pramana-research/filing-evidence` | Date |
|---|---|---|
| Protocol v1.0 (hypotheses H1–H8, setups, metrics, statistics) | [`00260c4`](https://github.com/pramana-research/filing-evidence/commit/00260c43e78ad0f53fcc23ddec6645b97c2559b7) | 2026-11-21 13:31 IST |
| Dataset built, validated and frozen (fingerprint `9a007d80…`), before any model ran | [`4f2ce0c`](https://github.com/pramana-research/filing-evidence/commit/4f2ce0c8953b92ef54d460835d196c7c43c9ecb8) | 2026-11-21 13:56 IST |

## Layout

| Path | What |
|---|---|
| `PROTOCOL.md` | the pre-registration: questions, data, setups, checks, metrics, statistics, deviations |
| `companies.yaml`, `eligibility.py`, `fetch.py` | the 100 companies, the SEC eligibility check, the download |
| `build.py`, `validate.py`, `freeze.py`, `dataset/` | build the 10,000 questions and difficulty tags, check them, freeze the fingerprint |
| `v1/` | unchanged copies of the v1 modules this study reuses (reader, builder, checker, EDGAR client) |
| `prompts/`, `models.yaml` | the prompt and retry messages; how each model is served and asked |
| `serve.py`, `runner.py`, `run.sh`, `watchdog.sh`, `emergency.sh` | serve a model with vLLM, run a setup, run the job queue with stop / resume, GPU guard rail |
| `results/<model>/<setup>/` | `summary.json`, `run.json` (answers on Hugging Face); `results/serve/` the server records |
| `analyze.py`, `results/analysis/` | per-sector metrics, H1–H6 (§10, §11) |
| `logs/` | build and run logs |

## Reproduce

```bash
uv sync --all-extras                      # Python 3.12; vLLM 0.33.0 for serving
cp .env.example .env                      # HF_TOKEN for gated models
uv run python hf_data.py pull             # questions, pages, all replies; verified against dataset/FROZEN.json
uv run pytest                             # build rules and fingerprint

# re-grade every stored reply (no GPU)
uv run python runner.py qwen3.5-9b C1 --regrade

# the analysis
uv run --extra analysis python analyze.py

# run the job queue yourself (one 24 GB GPU): start / stop / status
bash run.sh start
```

Rebuilding the dataset from SEC EDGAR (`fetch.py`, then `build.py`) needs `SEC_USER_AGENT` in `.env`; the result is
checked against the same fingerprint.

## Licence

Code: Apache 2.0 ([LICENSE](LICENSE)). Data on Hugging Face: CC BY 4.0 ([LICENSE-DATA.txt](LICENSE-DATA.txt)).
Copyright 2026 Pramana Research. Author: Krishna Nandula.

## Disclaimer

This is an independent community research project, carried out in a personal capacity; it does not represent the
views of any employer or other organisation. It is not affiliated with, sponsored or endorsed by any company or
model developer named here; all names and trademarks belong to their owners. Results describe specific model
versions under one fixed setup and are not a general judgement of any model. The data, results and code are provided
as is, without warranty, and may contain errors; check any figure against the original filing. Nothing here is
financial, investment or legal advice.
