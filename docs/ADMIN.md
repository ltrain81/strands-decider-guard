# Policy console guide

[한국어](ADMIN.ko.md)

The console lets anyone, developer or not, decide what the guard blocks. Saved changes reach every coding agent
(Claude Code, Kiro and Codex hooks) and the LiteLLM guardrail within **30 seconds**, with no redeploy.

## Opening it

- **AWS:**
  - `make console` prints the URL; the deploy prints it too.
  - Create a login with `make add-admin ADMIN_EMAIL=you@example.com`, or pass `ADMIN_EMAIL=` to `make deploy`.
    Cognito emails a temporary password, and you choose a new one on first sign-in.
  - Console logins are separate from AWS access: only people with a login can change the policy.
- **Local:** `make local-console` opens `http://127.0.0.1:8770`, with no login.
  - Policies saved here go to `~/.decider-guard/policy.json`, which local-mode hooks (`make local`) read immediately.
- **Language:** use the **EN / 한국어** toggle in the header. The default follows the browser; add `?lang=ko` to a link to force one.

## Overview tab

The first screen: is the guard working, and what is it doing?

- **Health:** the guard (can it reach the model, which model and device), the GPU host (running or stopped),
  the policy (when and by whom it was last saved) and alerts (how many rules are on, and which are in alarm).
- **Numbers for the period** (1 hour to 30 days): checks, blocked and asked (with their share of all checks),
  p95 latency, and guard errors.
- **Charts:** decisions over time (allowed / asked / blocked) and latency (median and p95). Hover a chart to see
  the values for each time bucket.
- **Breakdowns:** why things were blocked (by information type or custom rule) and which tools sent the checks.
- **Latest blocks and asks**, with a link to the full log. "Auto-refresh" reloads the tab every minute.

## Policy tab

### Sensitivity

| Choice | When | Benchmark (held-out half): recall · false positives · on developer text |
|---|---|---|
| Lenient | false alarms that block work are the bigger problem | 63 % · 1.4 % · 0 % |
| **Balanced (recommended)** | most teams | 70 % · 3.4 % · 3.1 % |
| Strict | finance, healthcare: missing something is worse | 76 % · 4.7 % · 6.2 % |

### Actions by information type

Pick **Block**, **Ask** or **Allow** for each type:
- **Block:** the agent cannot read, write or send it to the model.
- **Ask:** Claude Code asks the user "continue?". Kiro, Codex and LiteLLM cannot ask, so they block.
- **Allow:** the type is not checked.

**HR / legal / private life** covers a specific person's disciplinary or HR matter, legal case, criminal record, immigration status,
religion, political views, union membership, sexual orientation or family situation. These are sensitive data under most privacy laws, and
regexes cannot find them.

"Resident registration number" is found by its format. The model's own ID judgement follows "Government ID",
so change the two together.

### Your own rules

Write what you want to stop as a **question that can be answered yes or no**. There are no regexes or keyword
lists: the model answers your question on every check.

Good questions:
- Does the text include unreleased schedules, revenue or launch plans for project 'Phoenix' (PHX)?
- Does the text include an employee's salary, compensation or performance review?
- Does the text include contract amounts or terms agreed with a customer?

Tips:
- **One topic per question.** Mixing topics blurs the answer.
- **Include other spellings and code names**, e.g. `Phoenix (PHX)` or `Phoenix(피닉스)`. In our tests a sentence that
  used only the Korean spelling was missed.
- **Be specific.** "Unreleased launch dates?" works better than "anything confidential?".
- Each rule has its own sensitivity: set rules you must not miss to **Strict**.
- Before saving, use the **Test** tab: try one sentence that should be blocked and one that should pass.

Up to 20 rules. More rules add almost no latency, because they are extra questions about text the model has already read.

### Exceptions (allowlist)

- **Email domains:** addresses in these domains (e.g. your company's) are removed before checking.
- **Words to ignore:** fake test names (`Jane Doe`), a public support number, and so on.

Allowlisted values are removed from the text before it is checked. With `Jane Doe` allowlisted,
"Jane Doe is treated for depression" no longer names a person, so it passes. **Do not add real people's names.**

### Block message

Shown to developers when something is blocked. A good place for your support channel.

### Saving

When "You have unsaved changes" appears at the bottom, click **Save and apply**. **Discard** returns to the last saved policy.

## Test tab

- Paste text and click **Check**. It uses the **current, unsaved** settings.
- The result is Blocked, Needs confirmation or Allowed, with the reasons, e.g.
  "Health / medical (model: sensitive 97%, specific person 65%)".
- Tested text is not logged and does not count in Activity.

## Logs tab

- **Decision log:** every check the guard made.
  - Filter by period, decision, tool, information type (or custom rule) and target. The target is a file name, `prompt`, `bash` and so on.
  - Click a row for its details, including the request ID for CloudWatch.
  - **Export CSV** downloads what is on screen.
  - **No text is stored anywhere:** the log holds the decision, tool, target, types, size and latency.
- **Admin activity:** who saved the policy or changed alerts, and exactly what changed.
  For example "Sensitivity: Balanced → Strict" or "Rule added: Project Atlas".
- On AWS this reads CloudWatch Logs, which can take a few seconds for long periods.

## Alerts tab

AWS only. Alerts email people when the guard needs attention.

- **Recipients:**
  - Add email addresses. AWS sends each new address a confirmation email, and alerts start after the recipient clicks "Confirm subscription".
  - The status shows *Waiting for confirmation* until then.
- **Rules**, each switched on or off, with a live state (OK / In alarm / Waiting for data):

| Rule | Fires when | Default |
|---|---|---|
| Guard down | the 5-minute health check cannot reach the model for 10 minutes | on |
| Guard errors | the guard Lambda returns an error | on |
| Block spike | more than *N* blocks in 5 minutes | off, N = 20 |
| Slow checks | p95 latency above *N* ms for 10 minutes | off, N = 3000 |

- **Send test notification** checks that the emails arrive.
- A stopped GPU host (`make stop`) triggers *Guard down*. Turn that rule off first if you stop the host on purpose.

## History tab

- Every save is a version, with who saved it and when.
- **Compare** shows what loading that version would change.
- To roll back, click **Load**, review the policy on the Policy tab, then click **Save and apply**.

## Good to know

- The guard caches the policy for 30 seconds, so the old policy may apply for up to 30 seconds after a save.
- If the guard cannot read the policy, it **keeps enforcing the last policy it read**. With no policy at all, it uses
  the defaults: every type blocked, balanced sensitivity.
- Quality was checked on a few dozen synthetic sentences. Use the Test tab with real examples from your own work.
