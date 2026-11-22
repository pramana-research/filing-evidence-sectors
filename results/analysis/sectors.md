# Filing-Evidence Sectors: per-sector results

## C1 · accuracy (% of answerable)

| Model | All | Banks | Energy (power and utilities) | Healthcare | Insurance | Media | Metals and mining | Oil and gas | Real estate | Technology | Telecom |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-9b | **86.4** | 87.0 | 89.8 | 88.9 | 82.2 | 86.1 | 88.3 | 85.1 | 89.0 | 86.0 | 81.8 |
| gpt-oss-20b | **78.6** | 80.1 | 84.6 | 79.6 | 77.1 | 78.4 | 74.7 | 74.6 | 80.4 | 80.3 | 76.4 |
| glm-4.6v-flash | **76.9** | 77.4 | 83.2 | 77.1 | 75.6 | 77.4 | 77.0 | 72.5 | 76.2 | 77.1 | 75.4 |
| granite-4.2-8b | **75.9** | 76.1 | 84.3 | 77.9 | 72.0 | 74.3 | 75.0 | 72.5 | 73.3 | 78.1 | 75.3 |
| ministral-3-8b | **71.9** | 72.1 | 78.7 | 74.2 | 71.8 | 73.4 | 68.9 | 66.0 | 70.8 | 72.8 | 70.8 |
| qwen3-8b (suppl.) | **70.8** | 68.8 | 77.0 | 68.3 | 70.8 | 69.7 | 69.8 | 65.3 | 76.2 | 71.1 | 70.9 |
| llama-3.1-8b | **64.4** | 65.8 | 71.8 | 62.6 | 62.8 | 66.7 | 63.1 | 63.0 | 64.8 | 64.3 | 59.4 |
| gemma-3-12b | **63.9** | 62.0 | 69.9 | 62.6 | 64.7 | 66.4 | 58.4 | 62.2 | 58.9 | 65.8 | 68.4 |
| phi-4 | **63.3** | 65.6 | 65.1 | 58.4 | 62.4 | 67.0 | 65.7 | 56.0 | 64.0 | 64.8 | 63.7 |
| nemotron-nano-9b-v2 | **45.9** | 47.7 | 52.9 | 46.6 | 41.9 | 45.7 | 47.8 | 43.7 | 43.7 | 45.1 | 43.7 |
| olmo-3-7b | **19.2** | 19.0 | 21.8 | 21.0 | 17.1 | 20.8 | 22.2 | 16.4 | 17.9 | 17.4 | 18.1 |
| *pooled, 10 main models* | **64.6** | 65.3 | 70.2 | 64.9 | 62.8 | 65.6 | 64.1 | 61.2 | 63.9 | 65.2 | 63.3 |

## C1 · confident-wrong (% of all)

| Model | All | Banks | Energy (power and utilities) | Healthcare | Insurance | Media | Metals and mining | Oil and gas | Real estate | Technology | Telecom |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-9b | **3.0** | 2.6 | 1.7 | 2.9 | 4.6 | 3.2 | 2.9 | 5.6 | 2.7 | 1.5 | 2.7 |
| gpt-oss-20b | **10.3** | 8.6 | 6.5 | 11.0 | 12.2 | 9.5 | 13.7 | 16.0 | 8.9 | 8.2 | 8.2 |
| glm-4.6v-flash | **9.8** | 9.2 | 7.8 | 11.2 | 11.8 | 8.1 | 11.7 | 14.7 | 9.0 | 8.2 | 6.0 |
| granite-4.2-8b | **7.7** | 6.4 | 4.8 | 7.9 | 10.6 | 7.2 | 8.8 | 12.6 | 6.2 | 6.4 | 6.3 |
| ministral-3-8b | **6.5** | 5.5 | 3.6 | 7.7 | 8.1 | 5.8 | 8.5 | 11.2 | 6.6 | 4.1 | 4.1 |
| qwen3-8b (suppl.) | **9.4** | 9.3 | 6.7 | 11.0 | 10.3 | 9.3 | 11.2 | 17.0 | 5.4 | 6.0 | 8.0 |
| llama-3.1-8b | **8.9** | 8.1 | 7.8 | 9.6 | 10.1 | 7.5 | 10.8 | 15.5 | 6.6 | 6.6 | 6.5 |
| gemma-3-12b | **10.4** | 11.5 | 9.3 | 13.4 | 9.4 | 8.5 | 11.0 | 16.5 | 8.9 | 7.2 | 8.6 |
| phi-4 | **14.9** | 15.1 | 15.9 | 17.9 | 16.0 | 12.1 | 13.6 | 23.3 | 11.5 | 13.6 | 9.8 |
| nemotron-nano-9b-v2 | **10.4** | 11.0 | 8.9 | 10.0 | 14.1 | 10.4 | 10.9 | 14.3 | 9.0 | 7.9 | 7.7 |
| olmo-3-7b | **8.5** | 7.9 | 11.0 | 8.0 | 9.8 | 7.4 | 7.8 | 9.7 | 6.1 | 9.5 | 7.7 |
| *pooled, 10 main models* | **9.0** | 8.6 | 7.7 | 10.0 | 10.7 | 8.0 | 10.0 | 13.9 | 7.5 | 7.3 | 6.8 |

## C2 · accuracy (% of answerable)

| Model | All | Banks | Energy (power and utilities) | Healthcare | Insurance | Media | Metals and mining | Oil and gas | Real estate | Technology | Telecom |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-9b | **87.0** | 87.2 | 90.1 | 89.7 | 82.7 | 86.9 | 89.1 | 85.7 | 89.6 | 86.6 | 82.1 |
| gpt-oss-20b | **80.6** | 82.8 | 86.9 | 81.4 | 78.7 | 80.1 | 76.6 | 75.5 | 82.4 | 82.9 | 78.3 |
| glm-4.6v-flash | **78.3** | 78.7 | 84.7 | 78.2 | 76.6 | 79.0 | 78.6 | 74.1 | 77.8 | 78.0 | 77.4 |
| granite-4.2-8b | **78.4** | 78.3 | 86.7 | 80.3 | 74.8 | 78.3 | 77.1 | 74.5 | 77.8 | 79.7 | 77.0 |
| ministral-3-8b | **74.5** | 74.6 | 80.9 | 77.2 | 73.6 | 76.8 | 72.2 | 68.0 | 74.2 | 75.1 | 72.3 |
| qwen3-8b (suppl.) | **72.7** | 69.9 | 79.2 | 70.9 | 72.3 | 72.7 | 71.3 | 67.4 | 77.4 | 72.7 | 72.8 |
| llama-3.1-8b | **68.7** | 69.2 | 75.8 | 68.3 | 66.4 | 71.1 | 67.2 | 66.3 | 69.2 | 69.7 | 63.8 |
| gemma-3-12b | **66.7** | 64.6 | 72.1 | 65.2 | 67.8 | 69.0 | 61.8 | 64.4 | 62.8 | 69.2 | 70.3 |
| phi-4 | **65.5** | 68.4 | 67.3 | 60.9 | 64.6 | 69.3 | 67.3 | 57.6 | 67.1 | 66.4 | 65.7 |
| nemotron-nano-9b-v2 | **46.0** | 47.7 | 52.9 | 46.7 | 41.9 | 45.7 | 47.9 | 44.0 | 43.9 | 45.4 | 43.9 |
| olmo-3-7b | **19.2** | 19.1 | 21.8 | 21.0 | 17.1 | 20.8 | 22.3 | 16.4 | 18.0 | 17.4 | 18.2 |
| *pooled, 10 main models* | **66.5** | 67.1 | 71.9 | 66.9 | 64.4 | 67.7 | 66.0 | 62.6 | 66.3 | 67.0 | 64.9 |

## C2 · confident-wrong (% of all)

| Model | All | Banks | Energy (power and utilities) | Healthcare | Insurance | Media | Metals and mining | Oil and gas | Real estate | Technology | Telecom |
|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-9b | **3.1** | 2.7 | 1.7 | 2.9 | 4.7 | 3.3 | 2.9 | 5.6 | 2.9 | 1.5 | 2.7 |
| gpt-oss-20b | **10.6** | 8.7 | 6.8 | 11.6 | 12.6 | 9.6 | 13.9 | 16.2 | 9.2 | 8.6 | 8.6 |
| glm-4.6v-flash | **10.0** | 9.4 | 7.8 | 11.4 | 12.4 | 8.4 | 11.8 | 14.8 | 9.4 | 8.4 | 6.3 |
| granite-4.2-8b | **8.4** | 7.2 | 5.0 | 8.6 | 11.5 | 7.9 | 9.6 | 14.1 | 7.0 | 6.8 | 6.7 |
| ministral-3-8b | **7.0** | 5.8 | 4.0 | 8.1 | 8.7 | 6.3 | 9.3 | 12.0 | 6.9 | 4.6 | 4.6 |
| qwen3-8b (suppl.) | **10.0** | 10.3 | 7.3 | 11.4 | 11.1 | 9.6 | 11.9 | 17.6 | 5.5 | 6.7 | 8.6 |
| llama-3.1-8b | **10.5** | 9.8 | 8.9 | 11.0 | 12.5 | 9.8 | 12.3 | 17.1 | 7.6 | 8.2 | 7.9 |
| gemma-3-12b | **11.8** | 12.6 | 10.3 | 14.8 | 11.1 | 9.5 | 12.6 | 18.2 | 10.4 | 8.7 | 9.9 |
| phi-4 | **16.1** | 16.4 | 16.4 | 20.3 | 17.7 | 13.0 | 14.9 | 24.8 | 12.5 | 14.3 | 10.9 |
| nemotron-nano-9b-v2 | **10.5** | 11.0 | 8.9 | 10.2 | 14.1 | 10.4 | 10.9 | 14.4 | 9.1 | 7.9 | 7.8 |
| olmo-3-7b | **8.6** | 8.1 | 11.1 | 8.0 | 9.8 | 7.5 | 7.9 | 9.9 | 6.1 | 9.5 | 7.8 |
| *pooled, 10 main models* | **9.7** | 9.2 | 8.1 | 10.7 | 11.5 | 8.6 | 10.6 | 14.7 | 8.1 | 7.8 | 7.3 |

## H1 · accuracy differs across sectors

Wald omnibus, sector term; logit(correct ~ sector + model), C1, answerable, SE clustered by company. n = 90,020, 100 companies. χ²(9) = 15.5, p = 0.079 (before Holm correction across H1–H8).

| Sector | Odds ratio vs Energy (power and utilities) | 95% CI |
|---|---|---|
| Media | 0.78 | 0.60–1.01 |
| Banks | 0.77 | 0.63–0.94 |
| Technology | 0.76 | 0.61–0.96 |
| Healthcare | 0.75 | 0.59–0.95 |
| Metals and mining | 0.72 | 0.52–1.00 |
| Real estate | 0.71 | 0.51–0.99 |
| Telecom | 0.69 | 0.47–1.01 |
| Insurance | 0.67 | 0.55–0.83 |
| Oil and gas | 0.62 | 0.35–1.10 |

## H2–H6 · what makes a datapoint hard

Logistic regression on all §6 tags + model fixed effect, C1, answerable, SE clustered by company; n = 89,780, 100 companies. Raw p (Holm across H1–H8 applied once H7, H8 are in).

| # | Claim | Odds ratio | 95% CI | p | Verdict |
|---|---|---|---|---|---|
| H2 | units stated away from the figure -> higher confident-wrong than units in the row label | 2.19 | 1.43–3.36 | 0.00033 | supported (before Holm) |
| H3 | accuracy decreases as figures on the line increase (OR per extra figure) | 0.86 | 0.82–0.91 | 1.7e-08 | supported (before Holm) |
| H4 | accuracy higher when the answer is the line's first figure (OR later vs first) | 0.69 | 0.64–0.74 | 8.1e-24 | supported (before Holm) |
| H5 | 10-Q: year-to-date (6 or 9 months) accuracy lower than 3 months (OR YTD vs 3 months) | 0.72 | 0.62–0.82 | 2.3e-06 | supported (before Holm) |
| H6 | word-scale items fail mainly as unverifiable-right, not confident-wrong | 6.62 | 4.95–8.86 | 3.5e-37 | supported (before Holm) |

## H7 · thinking lowers confident-wrong; check + retry does not

Paired exact McNemar per model, Holm within each model's family. C2 on all 10,000 questions; C3 on the 1,000-question subset. Counts are confident-wrong answers (accuracy: correct of answerable).

| Model | CW C1 → C2 | p (Holm) | CW C1 → C3 | p (Holm) | Acc C1 → C2 | p (Holm) | Acc C1 → C3 | p (Holm) |
|---|---|---|---|---|---|---|---|---|
| gemma-3-12b | 1043 → 1181 | 5.7e-42 | — | — | 5755 → 6006 | 1.1e-75 | — | — |
| glm-4.6v-flash | 977 → 1001 | 3.5e-07 | 102 → 64 | 2e-05 | 6923 → 7048 | 1.9e-37 | 673 → 743 | 3.5e-07 |
| gpt-oss-20b | 1028 → 1058 | 3.7e-09 | 105 → 51 | 3.4e-09 | 7078 → 7252 | 3.3e-52 | 697 → 736 | 0.0039 |
| granite-4.2-8b | 772 → 844 | 1.3e-21 | 90 → 34 | 6.2e-09 | 6832 → 7062 | 4.6e-69 | 649 → 721 | 1.3e-05 |
| llama-3.1-8b | 891 → 1051 | 1.4e-48 | — | — | 5799 → 6185 | 2.5e-116 | — | — |
| ministral-3-8b | 652 → 703 | 8.9e-16 | — | — | 6476 → 6705 | 4.6e-69 | — | — |
| nemotron-nano-9b-v2 | 1042 → 1047 | 0.065 | 92 → 68 | 0.065 | 4128 → 4140 | 0.0015 | 412 → 519 | 1.7e-08 |
| olmo-3-7b | 849 → 857 | 0.016 | — | — | 1726 → 1730 | 0.12 | — | — |
| phi-4 | 1488 → 1612 | 9.4e-38 | — | — | 5695 → 5894 | 5e-60 | — | — |
| qwen3.5-9b | 304 → 309 | 0.062 | 34 → 15 | 0.0068 | 7780 → 7828 | 2.8e-14 | 743 → 689 | 0.0011 |

C3 lowers confident-wrong: **4 of 5 reasoning models** (pooled: 299 answers stop being confident-wrong, 108 start; p = 7.8e-22). C2 does not lower it: **10 of 10 models**; C2 raises it significantly: **8 of 10 models**.

## Holm correction across the hypotheses (H1–H7; H8 pending: needs R1)

| # | raw p | Holm p |
|---|---|---|
| H1 | 0.079 | 0.079 |
| H2 | 0.00033 | 0.00066 |
| H3 | 1.7e-08 | 6.7e-08 |
| H4 | 8.1e-24 | 4.8e-23 |
| H5 | 2.3e-06 | 6.9e-06 |
| H6 | 3.5e-37 | 2.5e-36 |
| H7 | 7.8e-22 | 3.9e-21 |
