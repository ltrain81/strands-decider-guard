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

## Policy tab

### Sensitivity

| Choice | When | What we saw on synthetic samples |
|---|---|---|
| Lenient | false alarms that block work are the bigger problem | missed some short health and driver's-license sentences |
| **Balanced (recommended)** | most teams | missed nothing; SQL such as `SELECT name, email …` gets **ask** |
| Strict | finance, healthcare: missing something is worse | missed nothing; masking examples (`010-XXXX-XXXX`) and SQL get **ask** |

### Actions by information type

Pick **Block**, **Ask** or **Allow** for each type:
- **Block:** the agent cannot read, write or send it to the model.
- **Ask:** Claude Code asks the user "continue?". Kiro, Codex and LiteLLM cannot ask, so they block.
- **Allow:** the type is not checked.

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

## Activity tab

- Checks, blocks and asks for the last 24 hours, 7 days or 30 days, broken down by information type and by tool.
- Recent blocks show the time, tool, target (e.g. `file:customers.csv`) and reason. **No text is stored anywhere.**
- On AWS the numbers come from CloudWatch Logs Insights and take a few seconds.

## History tab

- Every save is a version, with who saved it and when.
- To roll back, click **Load**, review the policy on the Policy tab, then click **Save and apply**.

## Good to know

- The guard caches the policy for 30 seconds, so the old policy may apply for up to 30 seconds after a save.
- If the guard cannot read the policy, it **keeps enforcing the last policy it read**. With no policy at all, it uses
  the defaults: every type blocked, balanced sensitivity.
- Quality was checked on a few dozen synthetic sentences. Use the Test tab with real examples from your own work.
