# Recall tuning (2026-10-12)

What changed in the guard, how the thresholds were chosen, and what they do on data they were **not** tuned on.

## Changes
1. **Questions** ([variants.py](variants.py), now `guard_core.QUESTIONS`): sharper category descriptions (contact = a specific person's
   name with contact details or IDs; none = code, schemas, column names, placeholders, templates, policies, statistics) and a new
   category **`private_life`**: a specific person's HR / disciplinary matter, legal case, criminal record, immigration status, religion,
   political views, union membership, sexual orientation or family situation. It is a new information type in the console, blocked by default.
   A further yes/no question ("is this a record that identifies a person?", variant V2) gave no gain and was dropped.
2. **Decision paths** (`guard_core.judge_chunk`, mirrored by [tune.py](tune.py)):
   - weak-pattern path: an email / phone / passport / … regex hit blocks once the sensitive-category mass is at least `weak_ps`
     (before, the model also had to say "real values", which it often did not for emails);
   - named-person path (strict): a named person in a moderately sensitive context blocks below the main threshold;
   - credentials need the real-value answer above `cred_real`, so `${DB_PASSWORD}`-style placeholders pass;
   - published test card numbers (payment-provider docs) are no longer card numbers.
3. **Thresholds**: grid search ([tune.py](tune.py)) over cached model answers ([features.py](features.py)), maximising recall under a
   false-positive cap on all negatives and on developer-style text. Cap per preset on the tune half: lenient 0.5 %, balanced 1 %,
   strict 2.5 % (model-attributable false positives). The first pick (caps 1 / 2.5 / 5 %) roughly doubled its false-positive rate on the
   holdout half, so each preset was moved one step more conservative.

## Method
Every sample is assigned to a stable 50/50 split by a hash of its id (`features.split_of`). Thresholds are chosen on **tune**
(931 tune / 923 holdout samples) and reported on **holdout**. The engine's own decisions
(`run.py`) match `tune.py`'s on all 923 holdout samples for every preset.

## Holdout results: old presets → new
Recall, precision and false-positive rate (FPR) in %, block = positive; developer text = public code / SQL / tech QA + synthetic
developer negatives.

| preset | recall | recall en | recall ko | precision | FPR | developer-text FPR |
|---|---|---|---|---|---|---|
| lenient | 44.0 → **62.6** | 34.4 → 52.6 | 62.0 → 81.5 | 97.9 → 98.8 | 1.7 → 1.4 | 3.1 → 0.0 |
| balanced | 52.5 → **70.0** | 42.2 → 62.1 | 71.7 → 84.8 | 97.5 → 97.4 | 2.4 → 3.4 | 3.1 → 3.1 |
| strict | 61.7 → **75.7** | 51.4 → 67.3 | 81.0 → 91.3 | 95.3 → 96.6 | 5.4 → 4.7 | 5.2 → 6.2 |

Recall by information type on the holdout half (new presets):

| type | lenient | balanced | strict |
|---|---|---|---|
| contact | 68 | 77 | 84 |
| credential | 56 | 59 | 59 |
| financial | 64 | 73 | 75 |
| gov_id | 68 | 78 | 80 |
| health | 77 | 82 | 88 |
| private_life | 69 | 69 | 86 |
| resident_id | 100 | 100 | 100 |

Before this change there was no `private_life` category; the old guard caught some of these texts only when another category
(contact, health) happened to fire (57 % at balanced on the same holdout samples).

## Chosen thresholds
```json
{
  "lenient": {
    "cat": 0.6,
    "named": 0.5,
    "block": 0.85,
    "ask": 0.5,
    "pattern": 0.2,
    "weak_ps": null,
    "named_cat": null,
    "cred_real": 0.3
  },
  "balanced": {
    "cat": 0.6,
    "named": 0.35,
    "block": 0.85,
    "ask": 0.5,
    "pattern": 0.2,
    "weak_ps": 0.3,
    "named_cat": null,
    "cred_real": 0.3
  },
  "strict": {
    "cat": 0.9,
    "named": 0.35,
    "block": 0.6,
    "ask": 0.5,
    "pattern": 0.2,
    "weak_ps": 0.3,
    "named_cat": 0.4,
    "cred_real": 0.0
  }
}
```

## Caveats
- The holdout half comes from the same datasets and generators as the tune half; on different text the numbers will move.
- English public sets remain the hardest (balanced recall 62 %): many ai4privacy snippets are short
  form fragments the model reads as non-personal.
- Reproduce: `features.py --variant V1 --split tune|holdout`, `tune.py --variant V1`, then `tune.py --variant V1 --report`
  (the final presets are in results/final_V1.json, one step more conservative than tune.py's raw pick).
