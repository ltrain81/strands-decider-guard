# strands-decider guard vs Amazon Bedrock Guardrails

Same samples, same labels (see README.md for the datasets; weak-only positives excluded). Block = positive. P = precision, R = recall, FPR = false-positive rate on negatives, all in %. Guardrails configs: **all types** = every identifier entity type plus NAME and ADDRESS, plus the two Korean regexes; **identifiers only** = without NAME / ADDRESS. Guardrails ran on the DRAFT version, classic tier, input source.

## PII detection per dataset

| set | system | pos | neg | P | R | F1 | FPR |
|---|---|---|---|---|---|---|---|
| ai4privacy | decider (balanced) | 200 | 100 | 93.9 | 23.0 | 36.9 | 3.0 |
| ai4privacy | Guardrails PII, all types | 200 | 100 | 81.2 | 84.0 | 82.6 | 39.0 |
| ai4privacy | Guardrails PII, identifiers only | 200 | 100 | 87.8 | 72.0 | 79.1 | 20.0 |
| gretel_finance | decider (balanced) | 200 | 150 | 97.9 | 47.5 | 64.0 | 1.3 |
| gretel_finance | Guardrails PII, all types | 200 | 150 | 85.3 | 98.5 | 91.4 | 22.7 |
| gretel_finance | Guardrails PII, identifiers only | 200 | 150 | 90.3 | 74.5 | 81.6 | 10.7 |
| nemotron | decider (balanced) | 200 | 0 | 100.0 | 56.5 | 72.2 | - |
| nemotron | Guardrails PII, all types | 200 | 0 | 100.0 | 96.5 | 98.2 | - |
| nemotron | Guardrails PII, identifiers only | 200 | 0 | 100.0 | 89.0 | 94.2 | - |
| kpii_bench | decider (balanced) | 200 | 0 | 100.0 | 72.0 | 83.7 | - |
| kpii_bench | Guardrails PII, all types | 200 | 0 | 100.0 | 100.0 | 100.0 | - |
| kpii_bench | Guardrails PII, identifiers only | 200 | 0 | 100.0 | 100.0 | 100.0 | - |
| ko_synth | decider (balanced) | 132 | 120 | 100.0 | 72.7 | 84.2 | 0.0 |
| ko_synth | Guardrails PII, all types | 132 | 120 | 83.6 | 96.2 | 89.4 | 20.8 |
| ko_synth | Guardrails PII, identifiers only | 132 | 120 | 84.2 | 60.6 | 70.5 | 12.5 |
| dev_public | decider (balanced) | 0 | 110 | - | - | - | 0.0 |
| dev_public | Guardrails PII, all types | 0 | 110 | 0.0 | - | - | 10.9 |
| dev_public | Guardrails PII, identifiers only | 0 | 110 | - | - | - | 0.0 |
| dev_synth | decider (balanced) | 0 | 100 | 0.0 | - | - | 9.0 |
| dev_synth | Guardrails PII, all types | 0 | 100 | 0.0 | - | - | 29.0 |
| dev_synth | Guardrails PII, identifiers only | 0 | 100 | 0.0 | - | - | 17.0 |

## Pooled by language (all positives vs all negatives, incl. developer negatives)

| lang | system | pos | neg | P | R | F1 | FPR |
|---|---|---|---|---|---|---|---|
| en | decider (balanced) | 600 | 420 | 94.8 | 42.3 | 58.5 | 3.3 |
| en | Guardrails PII, all types | 600 | 420 | 84.0 | 93.0 | 88.3 | 25.2 |
| en | Guardrails PII, identifiers only | 600 | 420 | 90.8 | 78.5 | 84.2 | 11.4 |
| ko | decider (balanced) | 332 | 160 | 100.0 | 72.3 | 83.9 | 0.0 |
| ko | Guardrails PII, all types | 332 | 160 | 90.8 | 98.5 | 94.5 | 20.6 |
| ko | Guardrails PII, identifiers only | 332 | 160 | 93.3 | 84.3 | 88.6 | 12.5 |

## False positives on developer-style text (code, SQL, configs, technical questions)

| system | samples | FPR |
|---|---|---|
| decider (balanced) | 210 | 4.3 |
| Guardrails PII, all types | 210 | 19.5 |
| Guardrails PII, identifiers only | 210 | 8.1 |

## Recall per information type (positives containing that type)

| type | decider (balanced) | Guardrails PII, all types | Guardrails PII, identifiers only |
|---|---|---|---|
| contact | 59.1 (618) | 99.4 (618) | 88.2 (618) |
| credential | 53.6 (153) | 90.8 (153) | 83.0 (153) |
| financial | 58.9 (253) | 95.7 (253) | 89.7 (253) |
| gov_id | 51.9 (208) | 92.8 (208) | 85.1 (208) |
| health | 67.0 (103) | 97.1 (103) | 75.7 (103) |
| resident_id | 100.0 (96) | 100.0 (96) | 100.0 (96) |

## Company rules: decider custom rules vs Guardrails denied topics

Each rule has positives and hard negatives (a same-named open-source project, negotiation tips, a contract template, already-published results). A sample counts as blocked if any rule/topic fired.

| rule | system | pos | neg | P | R | F1 | FPR |
|---|---|---|---|---|---|---|---|
| comp | decider custom rule (balanced) | 30 | 30 | 100.0 | 76.7 | 86.8 | 0.0 |
| comp | Guardrails denied topic | 30 | 30 | 57.1 | 53.3 | 55.2 | 40.0 |
| contract | decider custom rule (balanced) | 30 | 30 | 90.0 | 90.0 | 90.0 | 10.0 |
| contract | Guardrails denied topic | 30 | 30 | 59.5 | 73.3 | 65.7 | 50.0 |
| fin | decider custom rule (balanced) | 30 | 30 | 100.0 | 100.0 | 100.0 | 0.0 |
| fin | Guardrails denied topic | 30 | 30 | 65.6 | 70.0 | 67.7 | 36.7 |
| kestrel | decider custom rule (balanced) | 30 | 30 | 100.0 | 100.0 | 100.0 | 0.0 |
| kestrel | Guardrails denied topic | 30 | 30 | 56.6 | 100.0 | 72.3 | 76.7 |
| **all** | decider custom rule (balanced) | 120 | 120 | 97.3 | 91.7 | 94.4 | 2.5 |
| **all** | Guardrails denied topic | 120 | 120 | 59.3 | 74.2 | 65.9 | 50.8 |

## Latency (client round trip from Seoul-region caller, ms)

| system | p50 | p95 | p99 | note |
|---|---|---|---|---|
| Guardrails ApplyGuardrail (PII) | 140 | 252 | 303 | 1512 calls, 4 in parallel |
| decider guard Lambda | 243.0 | 287.6 | 317.8 | sequential, from perf.py |

## Cost

Measured on this run: 1512 PII checks used **1853 paid text units** (1.23 per check, average 511 characters); 240 topic checks used 240 units. This benchmark cost about $0.41 on Guardrails (two PII configs + topics).

Guardrails is billed per text unit (up to 1,000 characters), so long inputs such as file contents cost more. The decider guard is billed per GPU hour regardless of volume; one g6.xlarge sustained about 4 checks/s in perf.py.

| scenario | checks/month | text units | Guardrails PII only | Guardrails PII + topics | decider, hosts on 8h × 22d | decider, hosts 24/7 | avg checks/s → GPU hosts (peak 3× avg) |
|---|---|---|---|---|---|---|---|
| 10 devs × 200 checks/day × 22 days, 1500 chars avg | 44,000 | 88,000 | $9 | $22 | $187 | $735 | 0.07 → 1 host |
| 50 devs × 300 checks/day × 22 days, 2000 chars avg | 330,000 | 660,000 | $66 | $165 | $187 | $735 | 0.52 → 1 host |
| 200 devs × 300 checks/day × 22 days, 2000 chars avg | 1,320,000 | 2,640,000 | $264 | $660 | $374 | $1,470 | 2.08 → 2 hosts |
| 500 devs × 400 checks/day × 22 days, 3000 chars avg | 4,400,000 | 13,200,000 | $1,320 | $3,300 | $1,122 | $4,411 | 6.94 → 6 hosts |

Break-even (PII + topics, 2 text units per check): about 373,879 checks/month for a business-hours host, 1,470,356 for a 24/7 host. Lambda, S3, CloudWatch and the console add cents at these volumes. Prices: Seoul on-demand list prices; Savings Plans / Spot lower the GPU side, and Guardrails has no idle cost.
