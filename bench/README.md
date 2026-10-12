# Decider Guard benchmark

Measures how well `guard/guard_core.py` (regex + local strands-decider model) separates text that contains
PII / secrets / company-confidential content from ordinary developer text, and how fast it is locally and on the
deployed AWS Lambda. Results are in [RESULTS.md](RESULTS.md).

## What is measured

| Area | How |
|---|---|
| PII detection | `guard_core.check(text, policy={"sensitivity": preset})` for lenient / balanced / strict, default categories (all `block`). Precision, recall, F1 with **block** = positive and with **block or ask** = positive; FPR on negatives; recall per guard category; share of blocks produced by regex only vs regex + model vs model only. |
| Developer negatives | code, SQL schemas/queries, configs with placeholders, stack traces, technical questions, statistics, masked values, public figures (English and Korean). FPR per subset. |
| Korean | public Korean PII dataset + seeded synthetic Korean positives (values and context-only cases such as a named person's health / HR / legal situation) and Korean hard negatives. |
| Custom rules | 4 plain-language rules (invented project code name "Kestrel", employee compensation/reviews, customer contract terms, unpublished financials); 30 positives + 30 hard negatives each, English + Korean. Run (a) rules only, all PII categories `allow`, plus developer negatives; (b) rules + default PII categories. Rule sensitivity lenient / balanced / strict. |
| Latency | local `guard_core.check` sequential, ≥200 texts in length buckets <200, 200–1500, >1500 chars; AWS Guard Lambda: 220 sequential invocations (client round trip and the Lambda's own `latency_ms`), then concurrency 4 and 8 (100 calls each). |

A positive in the public datasets is a document whose annotations contain at least one span that maps to a guard
category (`datasets.py: LABEL_CAT`). Documents whose spans are only names, dates, companies, cities, URLs etc. are
kept as a separate *weak-only* group and reported as block rate only (the guard is not meant to block a bare name).

## Datasets

| Set | Source | License | Used |
|---|---|---|---|
| ai4privacy | [ai4privacy/pii-masking-400k](https://huggingface.co/datasets/ai4privacy/pii-masking-400k) (validation split, English rows) | `other` – custom ai4privacy license, read the dataset card before any commercial use | 200 positives, 50 weak-only, 100 negatives (rows with an empty `privacy_mask`) |
| gretel_finance | [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) (test split, English) | Apache-2.0 | 200 positives, 50 weak-only, 150 negatives (documents without `pii_spans`) |
| nemotron | [nvidia/Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) (test split) | CC-BY-4.0 | 200 positives, 50 weak-only (the set has practically no negatives) |
| kpii_bench | [woohyun212/k-pii-bench](https://huggingface.co/datasets/woohyun212/k-pii-bench) (test_track_a, Korean) | CC-BY-4.0 | 200 positives, 50 weak-only (no negatives) |
| dev_public | [databricks/databricks-dolly-15k](https://huggingface.co/datasets/databricks/databricks-dolly-15k) (tech-filtered QA, CC-BY-SA-3.0), [sahil2801/CodeAlpaca-20k](https://huggingface.co/datasets/sahil2801/CodeAlpaca-20k) (CC-BY-4.0), [b-mc2/sql-create-context](https://huggingface.co/datasets/b-mc2/sql-create-context) (CC-BY-4.0) | as listed | 40 + 40 + 30 negatives |
| ko_synth | `synth.py` (seeded) | – | 132 Korean positives (resident no., phone, e-mail, address, bank account, card, passport, health / HR / legal context), 120 Korean hard negatives |
| dev_synth | `synth.py` (seeded) | – | 60 English + 40 Korean developer negatives |
| rules | `rules.py` (seeded) | – | 4 rules × (30 positives + 30 hard negatives) = 240 |

Positives are sampled round-robin per guard category so that every category is represented. Texts longer than
4,000 characters are skipped. Exact dataset revisions (HF `sha`) are recorded in `data/sets/sources.json`.

Other candidates checked: ai4privacy 300k / 500k / openpii (same family, not needed), several small Korean sets
(townboy/korean-pii-dataset, seongyeon1/ko-pii-ner-100k, 1T/veil-pii-ko-synth, sehe1121/bc-pii-ko; all CC-BY or
Apache) – k-pii-bench was chosen because it has typed Korean entities (RRN, passport, NHIS, bank account).

## Reproduce

```bash
cd bench
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python pyarrow certifi boto3
../scripts/local-decider.sh start                # local strands-decider on 127.0.0.1:8000

.venv/bin/python -I datasets.py                   # download parquet to data/, build data/sets/*.jsonl
.venv/bin/python -I synth.py                      # Korean synthetic + developer negatives
.venv/bin/python -I rules.py                      # custom-rule set
.venv/bin/python -I run.py all --workers 1        # accuracy runs (~25 min on an M-series Mac)
.venv/bin/python -I perf.py local                 # local latency (~2 min)
.venv/bin/python -I perf.py aws                   # Lambda latency/throughput (430 invocations, needs AWS credentials)
.venv/bin/python -I report.py                     # results/metrics.json + RESULTS.md tables
```

All scripts are seeded (`SEED = 20261012`). `-I` keeps Python from importing anything from the working directory;
downloaded files are only parsed by pyarrow (and `ast.literal_eval` for Nemotron's span strings), never executed.
Per-sample outputs (`results/*.jsonl`) contain ids, labels, decisions and finding types only, no text.
`data/`, `results/` and `.venv/` are gitignored.

`run.py` memoises model answers per (chunk, question set) in `results/answer_cache.jsonl` (keyed by a SHA-256 of the
chunk), so the three presets reuse one model pass; the decision logic itself is the unmodified `guard_core.check`.
Latency is measured separately in `perf.py` without the cache.

## Caveats

- **Do not send concurrent requests to the local MPS decider.** With 6 parallel clients the server process aborted
  (Metal assertion "A command encoder is already encoding to this command buffer") and had to be restarted.
  `run.py` therefore defaults to `--workers 1`. Anything else that calls the local decider at the same time (e.g. the
  live hook) can trigger the same crash.
- Labels are the datasets' own annotations mapped to six guard categories; the mapping is a judgement call
  (e.g. PINs count as credentials, KR_NHIS as health, addresses as contact). Rows in ai4privacy with an empty mask
  and Gretel documents without spans were treated as negatives without manual review; some contain company or
  person names.
- Most public data is synthetic/LLM-generated, English-heavy and form-like; real developer traffic looks different.
  Only English rows of the multilingual sets were used.
- Synthetic Korean and rule sets come from a small number of templates (22 positive / 24 negative Korean templates,
  7–9 per rule side); numbers measure template coverage more than open-ended generalisation.
- The Lambda run uses the live policy stored in S3 (including whatever company rules are configured), so its
  question set differs from the local default-policy run.
- Results are for model `strands-decider-2B-qwen3.5-v1-2610` and the `guard_core.py` version present on the run date.

## Bedrock Guardrails comparison

`guardrails.py` runs the same samples through Amazon Bedrock Guardrails (`ApplyGuardrail`): a PII filter with all entity types,
one with identifiers only (no NAME / ADDRESS), and denied topics written from the four custom rules. It creates temporary guardrails
and deletes them afterwards (`--keep` to keep them); the 2026-10-12 run cost about $0.41.
`compare.py` writes [COMPARISON.md](COMPARISON.md): accuracy side by side, latency, and a monthly cost model.

```bash
.venv/bin/python -I guardrails.py --region ap-northeast-2 && .venv/bin/python -I compare.py
```

Findings (2026-10-12, holdout half, after the recall tuning in [TUNING.md](TUNING.md)):
- **PII identifiers, English:** Guardrails (identifiers only) has higher recall (74 % vs 62 % for the decider at balanced) but 2–3× the false
  positives (11.8 % vs 4.9 %; developer text 9.4 % vs 3.1 %). "All types" (with NAME) reaches 94 % but flags 20 % of developer text.
- **Korean:** decider 85 % recall with 0 % false positives vs Guardrails 72 % / 12 %.
- **HR / legal / private life:** decider 69 % (balanced) / 86 % (strict); Guardrails identifiers-only 4 %. "All types" catches them only
  through NAME, at the cost above.
- **Company rules:** decider custom rules F1 94 vs Guardrails denied topics 66 (denied topics fired on half the hard negatives).
- **Latency:** Guardrails p50 140 ms vs 243 ms for the decider Lambda round trip.
- **Cost:** see COMPARISON.md; Guardrails is cheapest for small teams, a scheduled Spot GPU host (~$133/month) wins as volume grows.
- Practical combination: Guardrails PII (identifiers only) as the server-side backstop, the decider for context, Korean, company rules and
  low false positives on code.
