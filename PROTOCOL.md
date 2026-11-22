# Filing-Evidence Sectors: protocol (pre-registration)

| | |
|---|---|
| Version | **1.0**, finalised 2026-11-21 (drafts: 0.1 initial; 0.2 robustness checks R1–R3 and H8) |
| Status | **final.** Written and committed before any question was built or any model was run. Every later change is logged in §14 |
| Owner | Pramana Research |
| Dataset | `pramana-research/filing-evidence-sectors` (Hugging Face), separate from the published Filing-Evidence v1 |

This document fixes the questions, data, setups, metrics and analysis in advance, so the results can't be shaped
after the fact. Anyone should be able to rerun the study from this document plus the code.

---

## 0 · Relationship to Filing-Evidence v1

- **v1 is not changed.** Its dataset, fingerprint (`4fa8f252…3c0a`), results and paper stay exactly as published. A test
  in the code repository fails if any v1 file or the v1 fingerprint changes.
- **Same method,** so results are directly comparable: the same page rendering (`ixbrl.py`), answer key from inline
  XBRL, answerability and wording rules (v1 §5), prompt (`prompts/v1.txt`), setups, checker and outcome definitions.
- **What is new:** ten sectors with ten companies each; 1,000 questions per sector (10,000 in total); difficulty factors
  tagged on every question; hypotheses about which datapoints are hard, fixed here **before** the data is built.
  These hypotheses come from an exploratory analysis of v1 (2026-11-21), so v1 cannot test them; this study can.

---

## 1 · Research questions

- **RQ1.** How does the accuracy of small open models at extracting a number **with checkable evidence** vary across
  ten industry sectors?
- **RQ2.** Which properties of a datapoint make it hard: where its units are stated, how many figures share its line,
  which column it sits in, its period, and whether it is written in words?
- **RQ3.** Do the v1 findings on the two training-free interventions (check + retry, thinking) hold on a larger and
  more varied set?

## 2 · Hypotheses (directions fixed in advance)

Tested on the plain setup (C1), pooled over the ten models with model as a fixed effect (§11), unless stated.

| # | Hypothesis | Test |
|---|---|---|
| **H1** | Accuracy differs across sectors. | Omnibus test of the sector term |
| **H2** | Items whose units are stated **away** from the figure (a table or page header, e.g. "(in thousands)") have a **higher confident-wrong rate** than items whose unit is in the row label (e.g. "per share", "%"). Share counts are the main case. | Units-location term on confident-wrong |
| **H3** | Accuracy **decreases** as the number of figures on the evidence line increases. | Figures-on-line term (ordinal) |
| **H4** | Accuracy is **higher** when the answer is the line's **first** figure than when it is a later one. | Column-position term |
| **H5** | In 10-Qs, year-to-date (6- or 9-month) figures have **lower accuracy** than 3-month figures from the same filings. | Period-length term, 10-Q only |
| **H6** | Amounts written with a word scale ("$12.6 billion") fail mainly as **unverifiable-right** (right value, quote does not show it in the answered form), not as confident-wrong. | Outcome mix for word-scale items vs others |
| **H7** | Replication of v1: thinking (C3) lowers the confident-wrong rate; check + retry (C2) does not. | Paired McNemar per model (§11) |
| **H8** | Rendering tables with aligned column headers (§12, R1) **lowers** wrong-period-or-column errors compared with the standard rendering. | Paired comparison on the robustness subset (§12) |

A hypothesis is **supported** when the pre-specified term is significant (α = 0.05, Holm-corrected across H1–H8) in
the stated direction. Effects in the other direction, or not significant, are reported as such.

---

## 3 · Models

The ten models of v1 (v1 §2), **at the same pinned Hugging Face revisions**, same precision and serving settings
(`models.yaml`). Qwen3-8B is run as a supplementary model, as in v1. If a revision is no longer downloadable, the
nearest available revision is used and logged (§14).

---

## 4 · Data

### 4.1 Companies (10 sectors × 10)

| Sector | Companies |
|---|---|
| **Banks** | JPM, BAC, WFC, C, USB, PNC, TFC, COF, MTB, FITB |
| **Technology** | AAPL, MSFT, NVDA, ORCL, ADBE, CSCO, IBM, INTC, CRM, QCOM |
| **Media** | DIS, CMCSA, NFLX, NYT, NXST, FOXA, NWSA, SIRI, LYV, OMC |
| **Telecom** | T, VZ, TMUS, CHTR, LUMN, TDS, IRDM, CABO, SATS, GSAT |
| **Insurance** | PGR, TRV, ALL, MET, PRU, AIG, CB, AFL, HIG, CINF |
| **Metals and mining** | FCX, NEM, NUE, STLD, CLF, AA, SCCO, RS, CMC, MP |
| **Energy (power and utilities)** | NEE, DUK, SO, D, AEP, EXC, SRE, XEL, PCG, ED |
| **Oil and gas** | APA, CVX, COP, EOG, OXY, DVN, PSX, MPC, VLO, SLB |
| **Healthcare** | JNJ, PFE, LLY, MRK, ABBV, UNH, TMO, ABT, MDT, CVS |
| **Real estate** | PLD, O, SPG, AMT, EQIX, PSA, WELL, DLR, CCI, VTR |

**Eligibility check before finalising (2026-11-21, `eligibility.py`, results in `eligibility.json`):** 93 of the
100 originally listed companies were eligible. Replaced by the next reserve in their sector: Warner Bros. Discovery
(WBD) and Paramount Skydance (PSKY), whose tickers are no longer in the SEC ticker map, by New York Times (NYT) and
Nexstar Media (NXST); ExxonMobil (XOM), whose ticker now maps to a new holding company with a 10-Q but no 10-K yet, by
APA Corp (APA); AvalonBay (AVB) and Equity Residential (EQR), whose tickers are no longer in the SEC ticker map, by
Crown Castle (CCI) and Ventas (VTR). The table above is the final list.

**Remaining reserves** (used in this order if a company fails during the build, §4.2; logged in §14):

| Sector | Reserves |
|---|---|
| Banks | KEY, RF, HBAN |
| Technology | AMD, TXN, INTU |
| Media | TGNA |
| Telecom | SHEN, ATNI, VSAT |
| Insurance | PFG, L, ACGL |
| Metals and mining | ATI, CRS, KALU |
| Energy | PEG, EIX, WEC |
| Oil and gas | FANG, HAL |
| Healthcare | BMY, AMGN, CI |
| Real estate | ARE |

### 4.2 Filings and eligibility

For each company: the **most recent 10-K and the most recent 10-Q filed on or before 2026-11-21**, from the SEC
submissions API, downloaded as in v1 (identifying User-Agent, at most 5 requests per second, sha256 recorded in
`sets/sectors/manifest.json`).

A company is **eligible** if both filings exist, carry inline XBRL, and render into pages under v1 §5. An ineligible
company is replaced by the next reserve in its sector, and the reason is logged (§14). (Applied once before finalising; see §4.1.)

### 4.3 Answer key

As v1 §3.3: from each filing's inline XBRL tags (concept, value after scale, sign and format, unit, period,
dimensions) and the page and line where the tagged figure is displayed.

### 4.4 Overlap with v1

About 30 companies are also in v1, and their latest filings may be the same documents. To keep the two datasets
independent, **no fact used by a v1 question** (same accession and XBRL fact id) is used here. The overlap in
companies and filings is reported in the dataset card.

### 4.5 Contamination

As v1 §3.4: recent filings, each model's release date reported next to the filing dates, and a memorised answer
still needs a verbatim quote from the shown pages.

---

## 5 · Slices and sampling (1,000 questions per sector, 10,000 in total)

The v1 slice definitions (v1 §4) are used unchanged. Target per sector:

| Slice | Per sector | Total |
|---|---|---|
| S1 Main statements, current period | 120 | 1,200 |
| S2 Main statements, prior period | 120 | 1,200 |
| S3 10-Q quarter vs year-to-date | 120 | 1,200 |
| S4 Notes | 160 | 1,600 |
| S5 Segments | 120 | 1,200 |
| S6 Numbers in prose | 120 | 1,200 |
| S7 Units and per-share | 140 | 1,400 |
| S8 Not in the provided pages | 100 | 1,000 |
| **Total** | **1,000** | **10,000** |

**Sampling rules** (fixed seed 20261121):
- about 100 questions per company, at most 130;
- in each sector, each slice drawn from at least 7 of the 10 companies;
- 10-K and 10-Q balanced where the slice allows;
- S8 split evenly across its kinds (a)–(d);
- at most 3 questions per XBRL concept per filing.

If a slice cannot reach its target in a sector (for example S5 in a sector with many single-segment companies), the
shortfall is filled by adding the sector's reserve companies, logged in §14. **The bar is never lowered** and no
sector has fewer than 1,000 questions.

## 6 · Difficulty tags (new; computed by code, fixed before any run)

Every question carries:

| Tag | Values |
|---|---|
| `sector` | one of the ten |
| `units_location` | in the row label · in the line · table or column header · page header · none (pure number) |
| `figures_on_line` | 1, 2, 3, 4, 5, 6+ |
| `value_position` | first · later (the answer's position among the line's figures) |
| `period_length` | instant · 3 months · 6 months · 9 months · 12 months |
| `word_scale` | yes if the figure is written with "million", "billion" or "thousand" |
| `has_dimension` | yes / no (segment or other axis member) |
| `form` | 10-K / 10-Q |

---

## 7 · What the model sees

Exactly as v1 §5: three pages (answer page, adjacent page, random distractor; for S8 three pages without the answer),
in random order with the fixed seed; the same rendering, answerability and wording rules; prompt `prompts/v1.txt`.

## 8 · Setups

| Setup | Scope |
|---|---|
| **C1 Plain** | all 10,000 questions, all models |
| **C2 Check + retry** | all 10,000 questions, all models |
| **C3 Thinking** | a **stratified subset of 1,000 questions** (100 per sector, proportional to the slice mix), drawn with seed 20261122 **before** any run; models with a reasoning mode only |

Decoding as v1 §6 (temperature 0; 512 new tokens for C1/C2, 8,192 for C3).

## 9 · Checker and outcomes

The v1 checker (v1 §7) and outcome definitions (v1 §8) are used unchanged. They define every **primary** result.

**Secondary analysis (fixed now, reported separately, never replacing a primary number):** a *format-tolerant*
grading for H6, in which an answer whose value equals the gold after converting a word scale ("12.6 billion" →
12,600 in millions) counts as correct when its quoted text shows the figure with that word scale.

## 10 · Metrics

As v1 §8, per model × setup, **for each sector and overall**:
- accuracy (correct ÷ answerable);
- confident-wrong rate (over all questions);
- abstention accuracy (S8);
- outcome mix and error taxonomy (v1 §9);
- per-slice and per-tag accuracy;
- mean and p95 tokens and seconds per answer; retry rate (C2).

## 11 · Statistics

- **Ranges:** 95% Wilson intervals for every rate. With 875 answerable questions per sector, an accuracy near 60% has
  a margin of about ±3 points.
- **Setup comparisons within a model:** paired exact McNemar tests, Holm-corrected within each model's family.
- **Model comparisons:** paired McNemar within each sector and overall, Holm-corrected within each family.
- **Hypotheses H1–H6:** logistic regression of the outcome (correct; confident-wrong for H2) on the tags of §6 plus a
  fixed effect for the model, with standard errors clustered by company. H7 by paired McNemar per model. H8 by a
  paired comparison of wrong-period-or-column errors, R1 vs C1 on the robustness subset, pooled over models (§12).
- All analyses and their code are written before the runs; any analysis added later is labelled **exploratory**.

---

## 12 · Robustness checks

Three checks show whether the headline findings depend on **how** the questions were asked rather than **what** was
asked. They run on the same stratified 1,000-question subset as C3 (§8), drawn before any run, in the plain setup (C1).
Their prompt, rendering and settings are fixed here, before any run.

| Check | What changes | Models | Question it answers |
|---|---|---|---|
| **R1 Table rendering** | Tables rendered as Markdown, one row per line, with the column headers as the table's first row (`\| Item \| 2025 \| 2024 \|`). Everything else as §7. | all 10 | Are column and period errors partly caused by flattening tables into text? (H8) |
| **R2 Prompt wording** | A second prompt (`prompts/v2-alt.txt`): the same JSON contract and rules, different instruction wording and a different worked example (a 10-Q with quarter and year-to-date columns). | all 10 | Do model rankings and findings hold under a different prompt? |
| **R3 Repeat run** | The identical C1 configuration run a second time. | 3 models: the best, a middle and the weakest by v1 C1 accuracy | How stable is a single run? |

**Grading.** The checker (§9) is applied to the page text exactly as shown in each check, so a quote copied from a
Markdown row is checked against the Markdown page. Outcome definitions are unchanged.

**What is reported and how it is judged:**
- for each model, accuracy and confident-wrong rate under each check next to C1 on the same subset, with paired
  McNemar tests (Holm-corrected within each check);
- **rank stability:** Kendall's τ between the model rankings under C1 and under R1 and R2;
- **R3:** the share of questions whose outcome changes between the two identical runs;
- a headline finding is called **robust** if its direction is unchanged under R1 and R2 and, where it is a
  difference between models or setups, the difference stays significant. Findings that are not robust are reported
  as such, with the check that changed them.

---

## 13 · Quality control

**Before any run (blocking, automatic):**
- all v1 builder regression tests pass, plus new tests for the sector set;
- every question passes the answerability and wording rules (v1 §5);
- a duplicate scan (no repeated question text; no v1 fact reused);
- slice and sector targets met;
- **freeze:** the dataset is fingerprinted (sha256 of the sorted question ids, gold values and page texts), as in v1.
  All results cite the fingerprint.

**Pipeline check (blocking):** one model (Qwen3.5-9B, C1) on 200 randomly chosen questions, to confirm the pipeline
runs end to end. Its outputs are logged separately and **not** used in any result.

**Human audit (non-blocking, continuous):** while and after the models run, the author reviews randomly drawn
filings in the Explorer tool: is the gold right (value, period, page), is the question answerable and unambiguous?
- target: **at least 500 questions** (5%), drawn at random across sectors with a recorded seed;
- reported with the dataset as an **audited error rate with a 95% interval**;
- every error found is fixed, logged in §14, and released as a new dataset version with a new fingerprint; results
  are re-graded and the change in every headline number is reported.

---

## 14 · Deviations log

Every change after this protocol is finalised, with its date and reason, and whether any result existed at the time.

| Date | Change | Results existed? |
|---|---|---|
| 2026-11-21 | **Deviation 1: sampling (§5).** The first build (draft fingerprint `31c5ed4bdf388a3b`, not frozen) produced 8,029 questions, not 10,000: S1–S4 met their targets in every sector, but S5 (segments), S6 (prose), S7 (units and per-share) and S8 fell short, because (i) v1's rule of one question per item **per company** binds at about 100 questions per company (e.g. Banks S7: 527 candidates, 83 chosen), and (ii) some sectors have few such facts (e.g. utilities: 31 segment candidates in total). Reserve companies (1–3 per sector) could not close gaps of this size. Changes: **(A)** one question per item **per filing** (a company's item may be asked from its 10-K and its 10-Q), keeping at most 3 questions per concept per filing; **(B)** S8 kinds are split evenly where possible and then topped up from any kind; each sector is then filled to exactly 1,000 questions from S4, S1, S2 and S3 in turn (20 at a time). Slice counts per sector are therefore no longer fixed: the actual counts, and every slice below its §5 target, are reported in `stats.json` and the paper. The hypotheses (§2) are tested on the difficulty tags (§6), which span all slices. | **No.** No model had been run on any sectors question |
| 2026-11-22 | **Deviation 2: exploratory extension (§17).** Adds a "cost and trust on one consumer GPU" analysis: energy and cost per 1,000 answers next to accuracy and confident-wrong, plus a 4-bit vs full-precision check. It is analysis-only for the main runs. The new runs (4-bit, §17.3) are supplementary. No hypothesis is attached. It is reported as exploratory, separately from H1–H8, and changes no frozen data, setup, metric or test in §§2–13. | **Yes.** C1 had finished for all models and C2 for six. The extension was added after those results were seen, which is why it is exploratory, not confirmatory |
| 2026-11-22 | **Deviation 3: analysis code written after the runs (§11).** §11 says the analysis code is written before the runs; the per-sector analysis (`sets/sectors/analyze.py`: §10 metrics, H1) was written after all runs finished. It implements §10–§11 as written, with no change to any metric, model set, test or threshold. | **Yes.** All runs had finished |

## 15 · Compute plan

On one NVIDIA RTX 4090, from v1's measured request times (an upper bound; requests run in parallel):

| Run | Estimate |
|---|---|
| C1, 10 models × 10,000 | ~140 h |
| C2, 10 models × 10,000 | ~170 h |
| C3, 5 models × 1,000 | ~87 h |
| R1 and R2, 10 models × 1,000 each | ~28 h |
| R3, 3 models × 1,000 | ~4 h |
| **Total** | **~17–18 days** |

## 16 · Publication

- **Dataset:** `pramana-research/filing-evidence-sectors` on Hugging Face, CC BY 4.0: questions, pages, every model
  answer (including reasoning), server logs, the audit records and the fingerprint.
- **Code:** in `github.com/pramana-research/filing-evidence` under `sets/sectors/`, Apache 2.0.
- **Report:** a research page on pramana-research.com, and a paper. Community research, not peer-reviewed unless
  stated.

## 17 · Exploratory extension: cost and trust on one consumer GPU (Deviation 2)

Added 2026-11-22, after C1 results were seen (§14). It is exploratory: no hypothesis, no confirmatory test, and it is
reported in its own section.

### 17.1 · Question

On a single consumer GPU, what does a trustworthy answer cost? Many users of filings (auditors, banks, regulated firms)
cannot send documents to a cloud API. For them the buying question is what one local GPU delivers. Public leaderboards
measure speed and price on cloud APIs and general tasks, not trust per unit of cost on long-document extraction.

### 17.2 · Cost and speed (analysis-only, from the main runs)

- **Per model and setup:** median and p95 seconds per answer, input and output tokens per answer, and answers per
  hour at the runner's fixed concurrency (as logged). Every number comes from the stored answers; nothing is re-run.
- **Energy:** GPU board power sampled each second with `nvidia-smi` during a short, dedicated measurement run per model
  (C1, a fixed random sample of 500 questions, `random.Random(0)`), at the same fixed 450 W power cap. The result is
  energy per 1,000 answers (kWh), the hardware-neutral headline.
- **Money:** kWh converted at stated tariffs, ₹ and US$, both given in the report. Optionally, a separately labelled
  "with hardware" figure that spreads the GPU's purchase price over a stated life.
- **Shown together with quality:**
  - accuracy vs energy per 1,000 answers;
  - confident-wrong vs energy per 1,000 answers;
  - correct answers per kWh;
  - confident-wrong per 1,000 answers.
- **Prefix caching:** the share of input tokens served from vLLM's prefix cache during the measurement run (many
  questions share pages), and seconds per answer with caching on and off for one model.
- **Limits, stated in the report:**
  - one hardware configuration (RTX 4090 at 450 W);
  - GPU board power only, not the whole system at the wall;
  - speed depends on the vLLM version and serving settings, all of which are recorded with the results.

### 17.3 · Quantisation and trust (supplementary runs)

- **Models:** the same 3 as R3 (best, middle and weakest by v1 C1 accuracy, §12).
- **Variant:** each in a published 4-bit build, pinned by revision. Use the developer's own 4-bit build if one exists,
  otherwise a widely used community quantisation. The exact repo, method and revision are recorded.
- **Run:** C1 on the 1,000-question subset (§8), with everything else as in §7–§9.
- **Compared with:** the same model's full-precision C1 answers on the same 1,000 questions. Reported:
  - accuracy and confident-wrong rate side by side;
  - a paired exact McNemar test on each;
  - the change in energy per 1,000 answers.
- **Question:** does 4-bit raise the rate of quietly wrong answers, beyond any loss in accuracy?
- **Compute:** about 3 × 1–2 h, run after the main queue. Labelled supplementary, like v1's Qwen3-8B runs.

### 17.4 · What it is not

It is not a speed leaderboard, and it does not rank hardware. It reports one fixed, documented configuration so that
others can scale the numbers to theirs.
