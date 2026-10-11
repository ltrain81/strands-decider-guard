# Recording a demo

[한국어](DEMO_VIDEO.ko.md)

Goal: a **~3 minute** screen recording that shows customer PII being stopped before it reaches a coding agent's model.
Split the screen: the agent works on the left, and decisions appear live on the right.

## 1. Prepare (30 minutes before)

```bash
make health          # AWS: the model is up (device: cuda). Local: scripts/local-decider.sh status
make install         # or make local, if the hooks are not installed yet
demo/run_demo.sh 1   # warm-up: gets Lambda and model cold starts out of the way
```

- **Data:** everything in `demo/en` and `demo/ko` is synthetic. Never show real customer data.
- **Keep off screen:**
  - AWS account IDs and ARNs, credentials (`~/.aws`, `env` output)
  - internal URLs and chat notifications
  - your user and host name: shorten the prompt with `PS1='$ '`
- Turn on **Do Not Disturb** and quit chat and mail apps.
- **Terminal:** 18–20 pt font, dark theme, 1920×1080 window, generous line spacing, cursor blink off.
- Split the screen (iTerm2 `⌘D`, or tmux):
  - Left, about 70%: the agent.
  - Right, about 30%: `demo/watch_audit.sh`. One line per decision: time, agent, tool, BLOCK (red) or ALLOW (green),
    latency and the detected types. It never prints text.

## 2. Tools

| Tool | When | How |
|---|---|---|
| macOS (`⌘⇧5`) | simplest | "Record selected portion" around the terminal; pick a microphone under Options |
| QuickTime | with voice-over | File → New Screen Recording |
| OBS Studio | webcam + screen, scene changes | window capture + video capture device |
| asciinema + agg | a GIF for a README | `asciinema rec demo.cast` → `agg demo.cast demo.gif` |

Recording the voice-over separately, while editing, usually sounds better.

## 3. Scenes (scripted)

`demo/run_demo.sh` types each prompt out and runs Claude Code, so takes come out consistent.
Press Enter to go to the next scene, or set `AUTO=4` to advance after 4 seconds.

```bash
demo/run_demo.sh               # all scenes (English; DEMO_LANG=ko for Korean)
demo/run_demo.sh 3 4           # retake scenes 3 and 4
MODEL=sonnet demo/run_demo.sh  # default is haiku, which answers fastest
```

| # | Screen | Expected | Suggested narration |
|---|---|---|---|
| 0 | the diagram in the README (10 s) | — | "We put a 2B decision model, strands-decider, in front of Claude Code. Prompts and tool calls are checked by a guard on AWS before the model sees them." |
| 1 | summarize `architecture.md` | allowed, normal summary | "Normal work just works. This document mentions customer contact fields, but holds no actual values." |
| 2 | prompt with a resident number | `UserPromptSubmit operation blocked by hook` + masked reason | "Paste a national ID and the model is never called. The reason is shown masked." |
| 3 | read `customers.csv` | Read denied: SSN, emails, phones | "When the agent tries to read the customer list, the file is checked first and the read is denied." |
| 4 | read `support_ticket.txt` | Read denied: health / medical | "**This is the key part.** There is no number here for a regex to catch, but the model judges it to be a named person's health information and blocks it, in a few hundred milliseconds." |
| 5 | ask it to run `cat customers.csv` | Bash denied | "Going through the shell doesn't help: the files a command reads are checked too." |
| 6 | close-up of the decision log (10 s) | BLOCK / ALLOW lines | "The log keeps decisions, types and latency. Never the text." |

In scene 4, zoom in on the probabilities (e.g. `sensitive 0.984, specific person 0.891`). That is what sets this
apart from rule-based DLP.

## 4. Optional scenes

- **Interactive Claude Code:** `cd demo/en && claude`, then type the same prompts. This looks more natural.
  - An **ask** verdict shows a confirmation dialog.
  - The `#pii-ok` prefix passes only *uncertain* prompts. A resident number is blocked even with it.
- **Kiro CLI:** `cd demo/en && kiro-cli chat`, then "read customers.csv": the tool call is blocked.
  Say plainly that Kiro CLI cannot block prompts; the model is warned instead.
- **Codex CLI:** `cd demo/en && codex`, then "cat customers.csv". Approve the hooks with `/hooks` before you record.
- **Policy console:**
  - Add a rule on camera, e.g. from the "Unreleased project details" template.
  - On the Test tab, check "Phoenix launches next March…": it is blocked. Save.
  - Show that the next agent request is blocked by the new rule.
- **LiteLLM (server-side):** after [LITELLM.md](LITELLM.md), send the same request with curl and show the HTTP 400.
  This lands the point "even if a user removes the hook, the proxy blocks it".
- **Operations:**
  - `make health` shows the model on the GPU.
  - In CloudWatch Logs, the guard Lambda's lines hold decisions, types and sizes but no text. Blur the account ID.

## 5. Tips

- The first request can take 1–3 s longer (cold start). Always warm up.
- Answers vary slightly between runs. Retake scenes and cut the best ones together.
- Each scene starts with `clear`, which gives clean cut points.
- Speed up the waiting parts 1.5–2× in editing; keep the block messages at normal speed.
- Use the scene titles the script prints (`[n/5] …`) as captions.

## 6. Checklist

- [ ] `make health` is OK and you warmed up
- [ ] no account IDs, credentials, real names or internal information on screen
- [ ] Do Not Disturb on, notifications off
- [ ] font ≥ 18 pt, decision log running on the right
- [ ] scenes 1–5 recorded, plus a close-up of the scene 4 probabilities
- [ ] afterwards, stop paying for the GPU: `make stop` or `make destroy`
