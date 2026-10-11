# Benchmark results
Generated 2026-10-12 08:17 KST by `report.py`. Model `strands-decider-2B-qwen3.5-v1-2610` on `mps` (local strands-decider). Percentages; P = precision, R = recall, FPR = false-positive rate on negatives. "block" = only block counts as positive; "block/ask" = block or ask counts as positive. No sample text appears in this file.
## Sample counts
| set | positives | weak-only (names/dates) | negatives |
|---|---|---|---|
| ai4privacy | 200 | 50 | 100 |
| dev_public | 0 | 0 | 110 |
| dev_synth | 0 | 0 | 100 |
| gretel_finance | 200 | 50 | 150 |
| ko_synth | 132 | 0 | 120 |
| kpii_bench | 200 | 50 | 0 |
| nemotron | 200 | 50 | 0 |
| rules | 120 | 0 | 120 |

## PII detection per dataset and preset
Datasets without negatives have no precision/FPR on their own (see pooled table).
| set | preset | pos | neg | P block | R block | F1 block | FPR block | P block/ask | R block/ask | F1 block/ask | FPR block/ask |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ai4privacy | lenient | 200 | 100 | 94.7 | 18.0 | 30.3 | 2.0 | 90.2 | 18.5 | 30.7 | 4.0 |
| ai4privacy | balanced | 200 | 100 | 93.9 | 23.0 | 36.9 | 3.0 | 93.1 | 27.0 | 41.9 | 4.0 |
| ai4privacy | strict | 200 | 100 | 92.9 | 32.5 | 48.1 | 5.0 | 92.6 | 37.5 | 53.4 | 6.0 |
| gretel_finance | lenient | 200 | 150 | 98.7 | 38.0 | 54.9 | 0.7 | 98.7 | 38.0 | 54.9 | 0.7 |
| gretel_finance | balanced | 200 | 150 | 97.9 | 47.5 | 64.0 | 1.3 | 97.0 | 48.0 | 64.2 | 2.0 |
| gretel_finance | strict | 200 | 150 | 97.3 | 54.0 | 69.5 | 2.0 | 96.5 | 55.0 | 70.1 | 2.7 |
| nemotron | lenient | 200 | 0 | - | 49.0 | - | - | - | 49.5 | - | - |
| nemotron | balanced | 200 | 0 | - | 56.5 | - | - | - | 57.0 | - | - |
| nemotron | strict | 200 | 0 | - | 64.5 | - | - | - | 67.0 | - | - |
| kpii_bench | lenient | 200 | 0 | - | 65.0 | - | - | - | 65.5 | - | - |
| kpii_bench | balanced | 200 | 0 | - | 72.0 | - | - | - | 76.0 | - | - |
| kpii_bench | strict | 200 | 0 | - | 75.0 | - | - | - | 78.5 | - | - |
| ko_synth | lenient | 132 | 120 | 100.0 | 64.4 | 78.3 | 0.0 | 95.5 | 64.4 | 76.9 | 3.3 |
| ko_synth | balanced | 132 | 120 | 100.0 | 72.7 | 84.2 | 0.0 | 90.7 | 73.5 | 81.2 | 8.3 |
| ko_synth | strict | 132 | 120 | 91.1 | 77.3 | 83.6 | 8.3 | 77.3 | 77.3 | 77.3 | 25.0 |

### Pooled by language (all positives vs all negatives incl. developer negatives)
| lang | preset | pos | neg | P block | R block | F1 block | FPR block | P block/ask | R block/ask | F1 block/ask | FPR block/ask |
|---|---|---|---|---|---|---|---|---|---|---|---|
| en | lenient | 600 | 420 | 94.6 | 35.0 | 51.1 | 2.9 | 93.8 | 35.3 | 51.3 | 3.3 |
| en | balanced | 600 | 420 | 94.8 | 42.3 | 58.5 | 3.3 | 91.3 | 44.0 | 59.4 | 6.0 |
| en | strict | 600 | 420 | 93.2 | 50.3 | 65.4 | 5.2 | 90.6 | 53.2 | 67.0 | 7.9 |
| ko | lenient | 332 | 160 | 100.0 | 64.8 | 78.6 | 0.0 | 98.2 | 65.1 | 78.3 | 2.5 |
| ko | balanced | 332 | 160 | 100.0 | 72.3 | 83.9 | 0.0 | 94.7 | 75.0 | 83.7 | 8.8 |
| ko | strict | 332 | 160 | 94.7 | 75.9 | 84.3 | 8.8 | 86.3 | 78.0 | 82.0 | 25.6 |

### Recall per guard category (all PII datasets, block / block-or-ask)
| category | n | lenient | balanced | strict |
|---|---|---|---|---|
| resident_id | 96 | 100.0 / 100.0 | 100.0 / 100.0 | 100.0 / 100.0 |
| gov_id | 208 | 44.7 / 45.2 | 51.9 / 54.8 | 60.6 / 64.4 |
| financial | 253 | 50.2 / 50.2 | 58.9 / 61.7 | 63.6 / 68.0 |
| contact | 618 | 51.3 / 51.5 | 59.1 / 60.5 | 64.7 / 65.9 |
| health | 103 | 58.3 / 60.2 | 67.0 / 72.8 | 73.8 / 79.6 |
| credential | 153 | 43.8 / 43.8 | 53.6 / 53.6 | 62.1 / 63.4 |

### Korean synthetic set: recall per kind (block / block-or-ask)
| kind | n | lenient | balanced | strict |
|---|---|---|---|---|
| contact | 30 | 66.7 / 66.7 | 83.3 / 83.3 | 86.7 / 86.7 |
| financial | 24 | 95.8 / 95.8 | 95.8 / 100.0 | 100.0 / 100.0 |
| gov_id | 12 | 50.0 / 50.0 | 66.7 / 66.7 | 83.3 / 83.3 |
| health | 18 | 66.7 / 66.7 | 88.9 / 88.9 | 100.0 / 100.0 |
| hr | 12 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| legal | 12 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| resident_id | 24 | 100.0 / 100.0 | 100.0 / 100.0 | 100.0 / 100.0 |

### Weak-only samples (only names, dates, companies, cities, URLs): share blocked / flagged
| set | lenient | balanced | strict |
|---|---|---|---|
| ai4privacy | 10.0 / 12.0 | 14.0 / 14.0 | 16.0 / 16.0 |
| gretel_finance | 0.0 / 0.0 | 2.0 / 2.0 | 6.0 / 6.0 |
| nemotron | 6.0 / 6.0 | 8.0 / 8.0 | 12.0 / 12.0 |
| kpii_bench | 2.0 / 2.0 | 14.0 / 14.0 | 28.0 / 30.0 |

### Developer-style negatives: false-positive rate (block / block-or-ask)
| subset | n | lenient | balanced | strict |
|---|---|---|---|---|
| dev_public:code | 40 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| dev_public:dolly | 40 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| dev_public:sql | 30 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| dev_synth:en | 60 | 15.0 / 15.0 | 15.0 / 30.0 | 23.3 / 38.3 |
| dev_synth:ko | 40 | 0.0 / 0.0 | 0.0 / 10.0 | 10.0 / 27.5 |

### Who produced the block (share of all blocks)
regex = strong pattern (resident number, card, keys), model not consulted; regex+model = weak pattern (email/phone/...) confirmed by the model; model = model only.
| set | preset | blocks | regex | regex+model | model |
|---|---|---|---|---|---|
| ai4privacy | lenient | 43 | 14.0 | 39.5 | 46.5 |
| ai4privacy | balanced | 56 | 10.7 | 42.9 | 46.4 |
| ai4privacy | strict | 78 | 7.7 | 35.9 | 56.4 |
| gretel_finance | lenient | 77 | 9.1 | 33.8 | 57.1 |
| gretel_finance | balanced | 98 | 7.1 | 31.6 | 61.2 |
| gretel_finance | strict | 114 | 6.1 | 29.8 | 64.0 |
| nemotron | lenient | 101 | 8.9 | 63.4 | 27.7 |
| nemotron | balanced | 117 | 7.7 | 64.1 | 28.2 |
| nemotron | strict | 135 | 6.7 | 62.2 | 31.1 |
| kpii_bench | lenient | 131 | 55.0 | 36.6 | 8.4 |
| kpii_bench | balanced | 151 | 47.7 | 36.4 | 15.9 |
| kpii_bench | strict | 164 | 43.9 | 34.8 | 21.3 |
| ko_synth | lenient | 85 | 38.8 | 38.8 | 22.4 |
| ko_synth | balanced | 96 | 34.4 | 40.6 | 25.0 |
| ko_synth | strict | 112 | 29.5 | 42.0 | 28.6 |
| all | lenient | 446 | 29.1 | 42.2 | 28.7 |
| all | balanced | 527 | 24.7 | 42.5 | 32.8 |
| all | strict | 621 | 20.9 | 41.1 | 38.0 |

## Custom rules only (all PII categories = allow)
Rule sensitivity = global preset in each column. P/R per rule: a rule "fires" when its own finding is raised; precision counts firings on every other sample (other rules' samples, hard negatives, developer negatives).
| rule | sensitivity | pos | P | R | F1 | R en | R ko | hard-neg FPR | FPR en | FPR ko | dev-neg FPR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Project Kestrel (unreleased) | lenient | 30 | 100.0 | 73.3 | 84.6 | 80.0 | 60.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Project Kestrel (unreleased) | balanced | 30 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Project Kestrel (unreleased) | strict | 30 | 88.2 | 100.0 | 93.8 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Employee compensation / reviews | lenient | 30 | 100.0 | 33.3 | 50.0 | 25.0 | 42.9 | 0.0 | 0.0 | 0.0 | 0.0 |
| Employee compensation / reviews | balanced | 30 | 100.0 | 76.7 | 86.8 | 75.0 | 78.6 | 0.0 | 0.0 | 0.0 | 0.0 |
| Employee compensation / reviews | strict | 30 | 100.0 | 86.7 | 92.9 | 75.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Customer contract terms | lenient | 30 | 100.0 | 63.3 | 77.6 | 66.7 | 58.3 | 0.0 | 0.0 | 0.0 | 0.0 |
| Customer contract terms | balanced | 30 | 65.9 | 90.0 | 76.1 | 100.0 | 75.0 | 10.0 | 14.3 | 0.0 | 0.0 |
| Customer contract terms | strict | 30 | 62.5 | 100.0 | 76.9 | 100.0 | 100.0 | 10.0 | 14.3 | 0.0 | 0.0 |
| Unpublished financials | lenient | 30 | 100.0 | 43.3 | 60.5 | 27.8 | 66.7 | 0.0 | 0.0 | 0.0 | 0.0 |
| Unpublished financials | balanced | 30 | 88.2 | 100.0 | 93.8 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Unpublished financials | strict | 30 | 65.2 | 100.0 | 78.9 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 |

Decision level on the rule set (any reason):

| preset | P block | R block | hard-neg FPR block | hard negs blocked by PII path | dev negs flagged |
|---|---|---|---|---|---|
| lenient | 100.0 | 53.3 | 0.0 | 0.0 | 0.0 |
| balanced | 97.3 | 91.7 | 2.5 | 0.0 | 0.0 |
| strict | 97.5 | 96.7 | 2.5 | 0.0 | 0.0 |

## Custom rules + default PII categories
Rule sensitivity = global preset in each column. P/R per rule: a rule "fires" when its own finding is raised; precision counts firings on every other sample (other rules' samples, hard negatives).
| rule | sensitivity | pos | P | R | F1 | R en | R ko | hard-neg FPR | FPR en | FPR ko |
|---|---|---|---|---|---|---|---|---|---|---|
| Project Kestrel (unreleased) | lenient | 30 | 100.0 | 76.7 | 86.8 | 80.0 | 70.0 | 0.0 | 0.0 | 0.0 |
| Project Kestrel (unreleased) | balanced | 30 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| Project Kestrel (unreleased) | strict | 30 | 88.2 | 100.0 | 93.8 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| Employee compensation / reviews | lenient | 30 | 100.0 | 33.3 | 50.0 | 25.0 | 42.9 | 0.0 | 0.0 | 0.0 |
| Employee compensation / reviews | balanced | 30 | 100.0 | 76.7 | 86.8 | 75.0 | 78.6 | 0.0 | 0.0 | 0.0 |
| Employee compensation / reviews | strict | 30 | 100.0 | 86.7 | 92.9 | 75.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| Customer contract terms | lenient | 30 | 100.0 | 63.3 | 77.6 | 66.7 | 58.3 | 0.0 | 0.0 | 0.0 |
| Customer contract terms | balanced | 30 | 65.9 | 90.0 | 76.1 | 100.0 | 75.0 | 10.0 | 14.3 | 0.0 |
| Customer contract terms | strict | 30 | 62.5 | 100.0 | 76.9 | 100.0 | 100.0 | 10.0 | 14.3 | 0.0 |
| Unpublished financials | lenient | 30 | 100.0 | 43.3 | 60.5 | 27.8 | 66.7 | 0.0 | 0.0 | 0.0 |
| Unpublished financials | balanced | 30 | 90.9 | 100.0 | 95.2 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |
| Unpublished financials | strict | 30 | 65.2 | 100.0 | 78.9 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |

Decision level on the rule set (any reason):

| preset | P block | R block | hard-neg FPR block | hard negs blocked by PII path |
|---|---|---|---|---|
| lenient | 100.0 | 54.2 | 0.0 | 0.0 |
| balanced | 97.3 | 91.7 | 2.5 | 0.0 |
| strict | 97.5 | 96.7 | 2.5 | 0.0 |

## Latency: local `guard_core.check` (sequential, default policy)
Measured 2026-10-12 01:17 KST, 240 texts after 5 warm-up calls. Milliseconds.
| bucket | n | p50 | p95 | p99 | mean chunks |
|---|---|---|---|---|---|
| all | 240 | 298.6 | 640.9 | 897.2 | - |
| len <200 | 80 | 242.3 | 279.8 | 288.9 | 0.95 |
| len 200-1500 | 80 | 298.6 | 437.1 | 596.9 | 0.94 |
| len >1500 | 80 | 607.3 | 709.2 | 943.7 | 1.84 |
| model called | 228 | 319.3 | 644.1 | 901.6 | - |
| regex short-circuit | 12 | 0.1 | 0.1 | 0.1 | 0 |

## Latency / throughput: AWS Guard Lambda
Measured 2026-10-12 01:07 KST in ap-northeast-2, 430 invocations in total (10 warm-up). Synthetic texts only. client = boto3 round trip from this laptop; reported = `latency_ms` inside the Lambda.
| mode | calls | client p50 | client p95 | client p99 | reported p50 | reported p95 | reported p99 | throughput rps | errors |
|---|---|---|---|---|---|---|---|---|---|
| sequential | 220 | 243.0 | 287.6 | 317.8 | 217.3 | 219.3 | 223.3 | - | 0 |
| concurrency 4 | 100 | 1193.4 | 1211.5 | 4122.5 | 1164.8 | 1183.0 | 1276.5 | 3.89 | 0 |
| concurrency 8 | 100 | 2891.7 | 3484.9 | 6232.0 | 2858.5 | 3286.7 | 3293.5 | 2.86 | 0 |

## Findings

Run date 2026-10-12, model `strands-decider-2B-qwen3.5-v1-2610` on Apple MPS, seed 20261012.

1. **Precision is high, recall on public English datasets is low.** On ai4privacy, Gretel and Nemotron the guard
   blocks only about 23–57 % of documents that contain categorised PII at `balanced` (strict: 33–65 %), while
   precision stays at 93–98 %. In about 60 % of the misses the model's "kind" question puts most of the probability
   on "none", so the text never reaches the category threshold. This happens with form-like, multilingual-style
   synthetic text where the PII value sits inside a long, otherwise neutral sentence. Short ai4privacy snippets
   are the weakest (about 22 % recall).
2. **Regex categories are reliable, model-only categories are not.** Resident registration numbers reach 100 %
   recall (pattern with check digit). Government IDs other than the Korean resident number, credentials (passwords,
   PINs, API keys written in prose), bank/routing numbers and contact data reach only about 52–59 % at `balanced`.
   About 35 misses on ai4privacy and 46 on Nemotron had a weak pattern hit (email/phone/...) that the model did
   not confirm.
3. **Korean does better than English.** k-pii-bench 72 % / ko_synth 73 % recall at `balanced` with 100 % precision
   and 0 % block-FPR on Korean negatives. Korean misses cluster in short texts (under 200 characters: 43 % recall
   vs 84 % for longer ones); in ko_synth, passport samples (67 %) and contact samples (83 %) are the weakest value kinds.
4. **HR and legal situations of a named person are never blocked** (0 % at every preset). There is no guard category
   for them; only health context is covered (89 % at `balanced`). This is a coverage gap, not a threshold problem.
5. **Developer negatives:** the public code, SQL and tech-QA samples had 0 % false positives at every preset. The
   synthetic negatives expose the weak spots: config files with variable placeholders for login secrets and `.env`
   style placeholder lines are *blocked* as credentials by the model; a well-known Luhn-valid test card number is
   blocked by the regex; schemas / SELECTs naming personal-data columns and a masking helper get `ask`.
   In Korean, at `strict`, schemas, SELECTs on personal-data columns, masked values, all-zero example numbers and
   validation code are flagged (block-or-ask FPR 25 %), so `strict` is too noisy for Korean developer text.
6. **Presets:** moving lenient → balanced → strict adds roughly 7–8 recall points per step on English and costs
   1–3 FPR points; `ask` adds little recall but most of the extra FPR. `balanced` is the best trade-off for Korean;
   for English the recall gap remains even at `strict`.
7. **Custom rules work well at `balanced`:** the invented project rule reached 100 % recall with no firing on the
   same-named open-source web server or the bird; financial and compensation rules reached 100 % / 77 %.
   `lenient` loses a lot of recall (33–73 %). The contract rule is the least precise: it also fires on
   compensation and project-plan positives and on 3 of 30 English hard negatives (contract-structure questions).
   At `strict` the financial rule fires on most project-plan positives. Cross-firing mostly lands on other
   confidential samples, so decision-level precision stays at 97 %. Rules never fired on developer negatives, and
   adding the default PII categories did not change rule results or add false blocks on the hard negatives.
8. **Latency:** local p50 about 0.3 s per check, about 0.6 s for texts over 1,500 characters (two chunks); strong
   regex hits short-circuit in under 1 ms. The Lambda adds only ~25 ms of overhead over its internal latency
   (p50 243 ms round trip). Concurrency does not raise throughput: the decider instance processes requests one at
   a time (about 4 req/s), so p50 grows to ~1.2 s at concurrency 4 and ~2.9 s at concurrency 8, with no errors.
9. **Operational:** the local MPS decider crashed under 6 concurrent requests (Metal command-buffer assertion);
   keep local callers sequential or add a lock/queue on the server.
