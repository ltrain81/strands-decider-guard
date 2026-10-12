# strands-decider guard vs Amazon Bedrock Guardrails

Same samples, same labels (see README.md for the datasets; weak-only positives excluded). PII tables use the **holdout half** only: the decider's thresholds were tuned on the other half (see TUNING.md); Guardrails was not tuned. Block = positive. P = precision, R = recall, FPR = false-positive rate on negatives, all in %. Guardrails configs: **all types** = every identifier entity type plus NAME and ADDRESS, plus the two Korean regexes; **identifiers only** = without NAME / ADDRESS. Guardrails ran on the DRAFT version, classic tier, input source.

## PII detection per dataset

| set | system | pos | neg | P | R | F1 | FPR |
|---|---|---|---|---|---|---|---|
| ai4privacy | decider (balanced) | 106 | 46 | 97.6 | 38.7 | 55.4 | 2.2 |
| ai4privacy | decider (strict) | 106 | 46 | 95.3 | 38.7 | 55.0 | 4.3 |
| ai4privacy | Guardrails PII, all types | 106 | 46 | 80.4 | 84.9 | 82.6 | 47.8 |
| ai4privacy | Guardrails PII, identifiers only | 106 | 46 | 88.0 | 76.4 | 81.8 | 23.9 |
| gretel_finance | decider (balanced) | 102 | 76 | 92.2 | 69.6 | 79.3 | 7.9 |
| gretel_finance | decider (strict) | 102 | 76 | 93.3 | 81.4 | 86.9 | 7.9 |
| gretel_finance | Guardrails PII, all types | 102 | 76 | 87.2 | 100.0 | 93.2 | 19.7 |
| gretel_finance | Guardrails PII, identifiers only | 102 | 76 | 90.4 | 73.5 | 81.1 | 10.5 |
| nemotron | decider (balanced) | 114 | 0 | 100.0 | 77.2 | 87.1 | - |
| nemotron | decider (strict) | 114 | 0 | 100.0 | 78.9 | 88.2 | - |
| nemotron | Guardrails PII, all types | 114 | 0 | 100.0 | 96.5 | 98.2 | - |
| nemotron | Guardrails PII, identifiers only | 114 | 0 | 100.0 | 88.6 | 94.0 | - |
| kpii_bench | decider (balanced) | 99 | 0 | 100.0 | 84.8 | 91.8 | - |
| kpii_bench | decider (strict) | 99 | 0 | 100.0 | 89.9 | 94.7 | - |
| kpii_bench | Guardrails PII, all types | 99 | 0 | 100.0 | 100.0 | 100.0 | - |
| kpii_bench | Guardrails PII, identifiers only | 99 | 0 | 100.0 | 100.0 | 100.0 | - |
| ko_synth | decider (balanced) | 58 | 64 | 100.0 | 89.7 | 94.5 | 0.0 |
| ko_synth | decider (strict) | 58 | 64 | 100.0 | 93.1 | 96.4 | 0.0 |
| ko_synth | Guardrails PII, all types | 58 | 64 | 81.8 | 93.1 | 87.1 | 18.8 |
| ko_synth | Guardrails PII, identifiers only | 58 | 64 | 82.1 | 55.2 | 66.0 | 10.9 |
| private_life | decider (balanced) | 51 | 13 | 100.0 | 68.6 | 81.4 | 0.0 |
| private_life | decider (strict) | 51 | 13 | 100.0 | 86.3 | 92.6 | 0.0 |
| private_life | Guardrails PII, all types | 51 | 13 | 100.0 | 100.0 | 100.0 | 0.0 |
| private_life | Guardrails PII, identifiers only | 51 | 13 | 100.0 | 3.9 | 7.5 | 0.0 |
| dev_public | decider (balanced) | 0 | 51 | - | - | - | 0.0 |
| dev_public | decider (strict) | 0 | 51 | - | - | - | 0.0 |
| dev_public | Guardrails PII, all types | 0 | 51 | 0.0 | - | - | 9.8 |
| dev_public | Guardrails PII, identifiers only | 0 | 51 | - | - | - | 0.0 |
| dev_synth | decider (balanced) | 0 | 45 | 0.0 | - | - | 6.7 |
| dev_synth | decider (strict) | 0 | 45 | 0.0 | - | - | 13.3 |
| dev_synth | Guardrails PII, all types | 0 | 45 | 0.0 | - | - | 31.1 |
| dev_synth | Guardrails PII, identifiers only | 0 | 45 | 0.0 | - | - | 20.0 |

## Pooled by language (all positives vs all negatives, incl. developer negatives)

| lang | system | pos | neg | P | R | F1 | FPR |
|---|---|---|---|---|---|---|---|
| en | decider (balanced) | 346 | 204 | 95.6 | 62.1 | 75.3 | 4.9 |
| en | decider (strict) | 346 | 204 | 94.3 | 67.3 | 78.6 | 6.9 |
| en | Guardrails PII, all types | 346 | 204 | 86.5 | 94.2 | 90.2 | 25.0 |
| en | Guardrails PII, identifiers only | 346 | 204 | 91.5 | 74.3 | 82.0 | 11.8 |
| ko | decider (balanced) | 184 | 91 | 100.0 | 84.8 | 91.8 | 0.0 |
| ko | decider (strict) | 184 | 91 | 100.0 | 91.3 | 95.5 | 0.0 |
| ko | Guardrails PII, all types | 184 | 91 | 91.4 | 97.8 | 94.5 | 18.7 |
| ko | Guardrails PII, identifiers only | 184 | 91 | 92.4 | 72.3 | 81.1 | 12.1 |

## False positives on developer-style text (code, SQL, configs, technical questions)

| system | samples | FPR |
|---|---|---|
| decider (balanced) | 96 | 3.1 |
| decider (strict) | 96 | 6.2 |
| Guardrails PII, all types | 96 | 19.8 |
| Guardrails PII, identifiers only | 96 | 9.4 |

## Recall per information type (positives containing that type)

| type | decider (balanced) | decider (strict) | Guardrails PII, all types | Guardrails PII, identifiers only |
|---|---|---|---|---|
| contact | 77.0 (322) | 83.5 (322) | 99.7 (322) | 89.1 (322) |
| credential | 58.8 (80) | 58.8 (80) | 92.5 (80) | 82.5 (80) |
| financial | 73.3 (135) | 74.8 (135) | 94.8 (135) | 89.6 (135) |
| gov_id | 78.2 (101) | 80.2 (101) | 94.1 (101) | 87.1 (101) |
| health | 82.1 (56) | 87.5 (56) | 96.4 (56) | 71.4 (56) |
| private_life | 68.6 (51) | 86.3 (51) | 100.0 (51) | 3.9 (51) |
| resident_id | 100.0 (45) | 100.0 (45) | 100.0 (45) | 100.0 (45) |

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
| Guardrails ApplyGuardrail (PII) | 141 | 253 | 316 | 825 calls, 4 in parallel |
| decider guard Lambda | 243.0 | 287.6 | 317.8 | sequential, from perf.py |

## Cost

Measured on this run: 825 PII checks used **1009 paid text units** (1.22 per check, average 498 characters); 240 topic checks used 240 units. This benchmark cost about $0.24 on Guardrails (two PII configs + topics).

Guardrails is billed per text unit (up to 1,000 characters), so long inputs such as file contents cost more. The decider guard is billed per GPU hour regardless of volume; one g6.xlarge sustained about 4 checks/s in perf.py.

### GPU host options

Measured on probe instances: g4dn.xlarge (T4) 0.78 s per short check and ~1 check/s; g6f fractional-GPU types ran on CPU with the GPU image (they need NVIDIA GRID drivers) at ~7 s per check, which also rules out CPU-only instances for interactive hooks.

| option | $/month (1 host) | checks/s per host | note |
|---|---|---|---|
| g6.xlarge on-demand, 24/7 | $735 | 3.5 | current default |
| g6.xlarge on-demand, weekdays 08-20 | $268 | 3.5 | --schedule; regex-only outside the window |
| g6.xlarge 1-yr reserved (no upfront), 24/7 | $483 | 3.5 | commitment; billed even when stopped |
| g6.xlarge Spot, 24/7 | $356 | 3.5 | --spot; interruptions fall back to regex-only |
| g6.xlarge Spot, weekdays 08-20 | $133 | 3.5 | --spot --schedule |
| g4dn.xlarge (T4) on-demand, weekdays 08-20 | $179 | 1.0 | ~3x slower: 0.8-1.0 s per check |

### Monthly cost by team size (number of GPU hosts in brackets)

| scenario | checks/month | Guardrails PII | Guardrails PII + topics | decider 24/7 | decider weekdays 08-20 | decider Spot weekdays 08-20 | decider g4dn weekdays 08-20 |
|---|---|---|---|---|---|---|---|
| 10 devs × 200/day, 1500 chars | 44,000 | $9 | $22 | $735 (1) | $268 (1) | $133 (1) | $179 (1) |
| 50 devs × 300/day, 2000 chars | 330,000 | $66 | $165 | $735 (1) | $268 (1) | $133 (1) | $358 (2) |
| 200 devs × 300/day, 2000 chars | 1,320,000 | $264 | $660 | $1,470 (2) | $536 (2) | $266 (2) | $895 (5) |
| 500 devs × 400/day, 3000 chars | 4,400,000 | $1,320 | $3,300 | $3,676 (5) | $1,341 (5) | $664 (5) | $2,684 (15) |

Guardrails has no idle cost and is cheapest for small teams; the decider's cost is flat per host, so it wins as volume or text length grows, and the schedule + Spot options cut it by about 80 % against on-demand 24/7. Lambda, S3, CloudWatch and the console add cents at these volumes.
