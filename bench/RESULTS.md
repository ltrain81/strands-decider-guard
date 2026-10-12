# Benchmark results
Generated 2026-10-12 09:51 KST by `report.py`. Model `strands-decider-2B-qwen3.5-v1-2610` on `mps` (local strands-decider). Percentages; P = precision, R = recall, FPR = false-positive rate on negatives. "block" = only block counts as positive; "block/ask" = block or ask counts as positive. No sample text appears in this file.
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
| private_life | 111 | 0 | 31 |
| rules | 120 | 0 | 120 |

## PII detection per dataset and preset
Datasets without negatives have no precision/FPR on their own (see pooled table).
| set | preset | pos | neg | P block | R block | F1 block | FPR block | P block/ask | R block/ask | F1 block/ask | FPR block/ask |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ai4privacy | lenient | 200 | 100 | 98.3 | 29.5 | 45.4 | 1.0 | 94.7 | 35.5 | 51.6 | 4.0 |
| ai4privacy | balanced | 200 | 100 | 97.6 | 41.5 | 58.2 | 2.0 | 94.9 | 47.0 | 62.9 | 5.0 |
| ai4privacy | strict | 200 | 100 | 93.5 | 43.0 | 58.9 | 6.0 | 92.6 | 44.0 | 59.7 | 7.0 |
| gretel_finance | lenient | 200 | 150 | 96.5 | 68.5 | 80.1 | 3.3 | 95.8 | 69.0 | 80.2 | 4.0 |
| gretel_finance | balanced | 200 | 150 | 94.3 | 74.0 | 82.9 | 6.0 | 93.7 | 74.0 | 82.7 | 6.7 |
| gretel_finance | strict | 200 | 150 | 94.8 | 82.0 | 87.9 | 6.0 | 94.3 | 82.0 | 87.7 | 6.7 |
| nemotron | lenient | 200 | 0 | - | 66.0 | - | - | - | 67.5 | - | - |
| nemotron | balanced | 200 | 0 | - | 75.5 | - | - | - | 77.0 | - | - |
| nemotron | strict | 200 | 0 | - | 77.0 | - | - | - | 78.0 | - | - |
| kpii_bench | lenient | 200 | 0 | - | 81.0 | - | - | - | 88.0 | - | - |
| kpii_bench | balanced | 200 | 0 | - | 83.5 | - | - | - | 89.0 | - | - |
| kpii_bench | strict | 200 | 0 | - | 90.0 | - | - | - | 91.0 | - | - |
| ko_synth | lenient | 132 | 120 | 100.0 | 84.8 | 91.8 | 0.0 | 91.9 | 85.6 | 88.6 | 8.3 |
| ko_synth | balanced | 132 | 120 | 100.0 | 89.4 | 94.4 | 0.0 | 92.2 | 90.2 | 91.2 | 8.3 |
| ko_synth | strict | 132 | 120 | 100.0 | 94.7 | 97.3 | 0.0 | 96.2 | 94.7 | 95.4 | 4.2 |
| private_life | lenient | 111 | 31 | 100.0 | 75.7 | 86.2 | 0.0 | 100.0 | 75.7 | 86.2 | 0.0 |
| private_life | balanced | 111 | 31 | 100.0 | 75.7 | 86.2 | 0.0 | 100.0 | 75.7 | 86.2 | 0.0 |
| private_life | strict | 111 | 31 | 100.0 | 90.1 | 94.8 | 0.0 | 100.0 | 90.1 | 94.8 | 0.0 |

### Pooled by language (all positives vs all negatives incl. developer negatives)
| lang | preset | pos | neg | P block | R block | F1 block | FPR block | P block/ask | R block/ask | F1 block/ask | FPR block/ask |
|---|---|---|---|---|---|---|---|---|---|---|---|
| en | lenient | 659 | 437 | 98.4 | 56.3 | 71.6 | 1.4 | 95.3 | 58.7 | 72.7 | 4.3 |
| en | balanced | 659 | 437 | 96.8 | 64.5 | 77.4 | 3.2 | 94.2 | 66.6 | 78.0 | 6.2 |
| en | strict | 659 | 437 | 95.4 | 69.2 | 80.2 | 5.0 | 94.5 | 69.8 | 80.3 | 6.2 |
| ko | lenient | 384 | 174 | 100.0 | 82.0 | 90.1 | 0.0 | 95.9 | 85.9 | 90.7 | 8.0 |
| ko | balanced | 384 | 174 | 100.0 | 84.9 | 91.8 | 0.0 | 96.0 | 88.0 | 91.8 | 8.0 |
| ko | strict | 384 | 174 | 100.0 | 91.9 | 95.8 | 0.0 | 98.1 | 92.4 | 95.2 | 4.0 |

### Recall per guard category (all PII datasets, block / block-or-ask)
| category | n | lenient | balanced | strict |
|---|---|---|---|---|
| resident_id | 96 | 100.0 / 100.0 | 100.0 / 100.0 | 100.0 / 100.0 |
| gov_id | 208 | 70.2 / 76.4 | 76.4 / 81.2 | 78.8 / 79.3 |
| financial | 253 | 68.0 / 71.1 | 76.3 / 79.1 | 78.3 / 79.4 |
| contact | 618 | 70.9 / 72.8 | 79.0 / 80.4 | 84.6 / 84.8 |
| health | 103 | 73.8 / 84.5 | 79.6 / 88.3 | 83.5 / 84.5 |
| credential | 153 | 62.7 / 62.7 | 65.4 / 65.4 | 64.7 / 66.0 |

### Korean synthetic set: recall per kind (block / block-or-ask)
| kind | n | lenient | balanced | strict |
|---|---|---|---|---|
| contact | 30 | 90.0 / 90.0 | 100.0 / 100.0 | 100.0 / 100.0 |
| financial | 24 | 95.8 / 100.0 | 95.8 / 100.0 | 100.0 / 100.0 |
| gov_id | 12 | 91.7 / 91.7 | 100.0 / 100.0 | 100.0 / 100.0 |
| health | 18 | 88.9 / 88.9 | 100.0 / 100.0 | 100.0 / 100.0 |
| hr | 12 | 0.0 / 0.0 | 0.0 / 0.0 | 41.7 / 41.7 |
| legal | 12 | 91.7 / 91.7 | 91.7 / 91.7 | 100.0 / 100.0 |
| resident_id | 24 | 100.0 / 100.0 | 100.0 / 100.0 | 100.0 / 100.0 |

### Weak-only samples (only names, dates, companies, cities, URLs): share blocked / flagged
| set | lenient | balanced | strict |
|---|---|---|---|
| ai4privacy | 14.0 / 20.0 | 18.0 / 24.0 | 24.0 / 24.0 |
| gretel_finance | 8.0 / 8.0 | 8.0 / 8.0 | 10.0 / 10.0 |
| nemotron | 26.0 / 26.0 | 26.0 / 26.0 | 34.0 / 34.0 |
| kpii_bench | 26.0 / 26.0 | 28.0 / 28.0 | 36.0 / 36.0 |

### Developer-style negatives: false-positive rate (block / block-or-ask)
| subset | n | lenient | balanced | strict |
|---|---|---|---|---|
| dev_public:code | 40 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| dev_public:dolly | 40 | 0.0 / 0.0 | 0.0 / 0.0 | 0.0 / 0.0 |
| dev_public:sql | 30 | 0.0 / 0.0 | 0.0 / 0.0 | 3.3 / 3.3 |
| dev_synth:en | 60 | 0.0 / 15.0 | 5.0 / 20.0 | 10.0 / 15.0 |
| dev_synth:ko | 40 | 0.0 / 10.0 | 0.0 / 10.0 | 0.0 / 5.0 |

### Who produced the block (share of all blocks)
regex = strong pattern (resident number, card, keys), model not consulted; regex+model = weak pattern (email/phone/...) confirmed by the model; model = model only.
| set | preset | blocks | regex | regex+model | model |
|---|---|---|---|---|---|
| ai4privacy | lenient | 67 | 9.0 | 44.8 | 46.3 |
| ai4privacy | balanced | 94 | 6.4 | 53.2 | 40.4 |
| ai4privacy | strict | 104 | 5.8 | 48.1 | 46.2 |
| gretel_finance | lenient | 146 | 6.2 | 28.8 | 65.1 |
| gretel_finance | balanced | 161 | 5.6 | 32.9 | 61.5 |
| gretel_finance | strict | 178 | 5.1 | 29.8 | 65.2 |
| nemotron | lenient | 145 | 6.2 | 59.3 | 34.5 |
| nemotron | balanced | 164 | 5.5 | 63.4 | 31.1 |
| nemotron | strict | 171 | 5.3 | 62.6 | 32.2 |
| kpii_bench | lenient | 175 | 41.1 | 37.1 | 21.7 |
| kpii_bench | balanced | 181 | 39.8 | 36.5 | 23.8 |
| kpii_bench | strict | 198 | 36.4 | 33.3 | 30.3 |
| ko_synth | lenient | 112 | 29.5 | 39.3 | 31.2 |
| ko_synth | balanced | 118 | 28.0 | 40.7 | 31.4 |
| ko_synth | strict | 125 | 26.4 | 38.4 | 35.2 |
| private_life | lenient | 84 | 0.0 | 0.0 | 100.0 |
| private_life | balanced | 84 | 0.0 | 0.0 | 100.0 |
| private_life | strict | 100 | 0.0 | 0.0 | 100.0 |
| all | lenient | 729 | 17.7 | 36.6 | 45.7 |
| all | balanced | 805 | 16.0 | 40.2 | 43.7 |
| all | strict | 883 | 14.6 | 37.0 | 48.4 |

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
