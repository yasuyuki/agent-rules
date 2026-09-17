# Opt-in Codex necessity review

The optional hook selects candidates, obtains restricted review and returns
model-visible handling through native synchronous Codex events. Normal rules or
skills installation does not enable it or call a model. This is a workflow
review, not a security approval or a tamper-proof boundary. Keep the current
task's execution contract in its existing issue rather than in hook settings.

## Configure an explicit scope

Install the `necessity` extra in the Python environment that runs placement
(`python -m pip install '.[necessity]'` from the source checkout). Bash uses
bashlex, Python uses `ast`, and PowerShell requires `pwsh` with its standard
parser. Missing parsers and unsupported syntax are unassessed, never approvals;
the selector does not execute inspected programs.

Prepare a private setup JSON. [necessity_install.py](../bin/necessity_install.py)
validates its exact schema; the settings you must choose are:

- `version: 1`, absolute workspace `scopes` and `excludes` arrays, and a private,
  Git-excluded absolute `state_dir`. Exclusions win; parent scopes cover children.
- Available review `model` and `effort`.
- Positive `deadline_seconds`, `max_input_bytes`, `max_output_bytes`,
  `reviews_per_session`, `retention_seconds`, and `max_sessions`, chosen from
  the site's allocation and a small authorized connection test. There are no
  production budget defaults. Retention must cover the native hook timeout
  (twice the deadline).
- Optional `shell` when payloads omit it: the confirmed native shell, not a
  guess from a tool label. Optional `codex_executable` selects a vendor executable
  when the site's usual entry adds incompatible sandbox/privilege arguments.
  Windows needs a native executable, not a batch shim; do not weaken the sandbox.

Input/output limits are byte limits, not violation scores. Allow room for the
request, candidate and observed generated file together; oversize selected input
stays unassessed. Image/base64 bodies are not review evidence. Start with a narrow
scope and explicitly exclude fixed experiments, comparisons and unattended wake
workspaces before considering normal development coverage.

## Install, accept and remove

From the public checkout use `python bin/place.py necessity --help` for the
management interface. The installed wheel exposes `agent-rules necessity`.
Install with `necessity install --codex-home PATH --settings FILE`, then run
`necessity check --codex-home PATH`. Installation preserves unrelated hooks and
does not set trust, permissions, feature flags or routing. An exact repeat is a
no-op; a changed/damaged installation needs resolution rather than overwriting.
To adopt changed source, remove the intact old owned installation first, then
install/check the new one.

Use Codex's official `/hooks` interface to inspect and trust the definitions,
including duplicates in other config layers. Start a new ordinary session and
verify event delivery and the restricted review round trip. Installation, trust,
loading and model-visible delivery are separate acceptance conditions; file
checks alone prove none of the latter. Existing sessions do not gain hooks
retroactively. Do not bypass native trust to make acceptance pass.

`necessity remove --codex-home PATH` removes only unchanged owned definitions
and implementation files, retaining unrelated hooks, settings, auth and decision
state. Resolve modified/co-owned groups first; do not leave a definition calling
a deleted file. Trust records remain owned by Codex.

## Diagnose and handle a delivered candidate

`necessity status --codex-home PATH` shows bounded verdicts and available usage
without saved prompts. No database means no persisted observations, not native
acceptance. Diagnostics describe pre-candidate failures using bounded reason and
digest metadata, without raw rejected input. They are unassessed and cannot be
resolved as candidates. Tiny budgets or unavailable state can prevent saving;
status reports omitted diagnostics rather than implying complete history.

After handling a candidate, use `necessity record` with its ID, an outcome
(`handled`, `deferred`, or `unassessed`) and concrete evidence. Recording cannot
change the original verdict, grant an exception or authorize a denied action.
Use the installing source's `bin/place.py` and the **same absolute Python
executable** for diagnosis/removal. A static invocation of management help,
check, status, record or remove is exempt from necessity decisions, including
when candidate state is broken; ordinary permissions and input validation still
apply. That exemption is not a bypass for installation, chained commands,
redirection, dynamic code or a different executable/entry.

## Interpret review without broadening authority

Current requests come from UserPromptSubmit; one explicitly referenced GitHub
issue/comment may be read through existing `gh` authorization. Ambiguous/missing
requests remain unassessed. Workers can inherit an unambiguous direct request in
the same native family/workspace; that does not inherit verdicts or approvals.
A normal negative invokes no model. Candidate responses separate the current
action decision from its disposition; a proposed integration is not permission
to implement another feature.

Grouping read-only observations is not by itself a reason to split work or
revise it. A revision needs unnecessary work to remove, a confirmed existing
entry to reuse or an actual work reduction. Read-only operations are not a
blanket exemption. The reviewer uses supplied evidence in a neutral temporary
cwd, read-only sandbox and no-approval mode, without project instructions,
skills/apps/plugins, collaboration, Web search or configured MCP access.
Unsupported override names and observed tool attempts invalidate assessment.
This is not a zero-tool guarantee against all hosted/specialized tools or a
same-user security boundary.

The hook never returns a security `allow`, rewrites tool input or replaces the
original PostToolUse result. PreToolUse may deny; PostToolUse failures return
nonblocking uncertainty so the already-executed result is delivered. Stop,
resume and compact preserve pending dispositions without an infinite Stop loop.
Hosted tools, subsequent `write_stdin` input, dynamic/unknown shell syntax and
paths outside observed workspace coverage remain gaps. Structured status, not
prose, supplies observed tool outcomes.

SQLite state holds bounded sanitized request material and decisions, not full
transcripts. Credential-like input prevents external review, but redaction is
not general secret detection. Keep state private and outside Git. Expiry is
opportunistic on later events; dormant installations may retain old records.
Missing/expired history after resume is unassessed, not evidence that earlier
candidates were handled. Use the task's saved result for evidence beyond retention.

## Verification

From the checkout, run the existing necessity modules through unittest:
`tests.test_necessity_select`, `tests.test_necessity_hook`,
`tests.test_necessity_install`, and `tests.test_necessity_review`.
[CI](ci.md) also checks setup/check/event/remove through the installed wheel.
PowerShell cases run where `pwsh` exists and are explicitly skipped otherwise.
Fixtures do not prove native trust, root/worker/resume/compact delivery or a real
model round trip; record those separately on each authorized target host.
