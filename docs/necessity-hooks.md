# Opt-in Codex necessity review

Implementation and acceptance target: automatic candidate selection, restricted
review, and model-visible handling through native synchronous Codex hooks.
Ordinary rules/skills installation does not enable this policy or call a model.
The current execution contract is maintained in the requesting issue, not here.

This is a workflow guardrail, not a security approval or a tamper-proof boundary.
Native hosted tools and subsequent `write_stdin` input are outside pre-tool
coverage. Unsupported syntax and incomplete inputs must remain unassessed.
Installation, trust, actual event delivery, and reviewer execution are separate
acceptance conditions. Existing sessions do not acquire hooks retroactively.

## Setup and removal

Install the optional `necessity` extra into the Python environment used for
placement (`pip install '.[necessity]'` for a source checkout). Ordinary package
installation remains dependency-free. Bash selection uses bashlex, Python uses
`ast`, and PowerShell uses its installed standard parser. Missing parsers and
unsupported syntax are explicit coverage gaps, never safe results. No inspected
program is evaluated by the selector. PowerShell requires `pwsh` on PATH.
The parser child opts out of PowerShell telemetry so first-use UUID creation
cannot block parsing on its telemetry mutex. This changes only the child's
environment; parser deadlines and fail-closed timeout handling are unchanged.

Prepare one private setup JSON with these fields; it is not a per-task input:

- `version`: `1`
- `scopes`, `excludes`: arrays of absolute workspace roots. Exclusions win.
- `state_dir`: private absolute Git-excluded state directory.
- `model`, `effort`: the site's already available review configuration.
- Optional `codex_executable`: absolute vendor executable when the normal site
  entry appends incompatible privilege/sandbox arguments. Otherwise the existing
  managed-entry resolver is used. Never loosen the review sandbox to use a wrapper.
  Windows requires a native `.exe`; `.cmd`/`.bat` shims are refused before launch.
- Optional `shell`: confirmed native shell (`bash`, `sh`, `powershell`, `pwsh`)
  when hook payloads omit it. Missing Windows shell information is unassessed;
  do not infer PowerShell or Bash from the canonical `Bash` hook name.
- `deadline_seconds`, `max_input_bytes`, `max_output_bytes`,
  `reviews_per_session`, `retention_seconds`, `max_sessions`: explicit positive
  integers chosen from the site's allocation and a small connection test.
  Retention must cover at least the native hook timeout (twice the deadline).

The installer intentionally has no production budget defaults. Input and output
limits are byte limits, not violation scores. `max_input_bytes` bounds selected
review text/evidence, not the raw native JSON envelope. Choose enough input space
for the request, candidate and observed generated file together; oversized
selected input remains unassessed. Native JSON is decoded before selecting the
event, workspace scope/exclusions and tool. Non-target events/tools and excluded
or outside workspaces return without opening state, sanitizing content or calling
a reviewer. Image/base64 result bodies are not review input; PostToolUse selects
only structured exit status and operation metadata. The hook timeout is twice the review deadline to allow parsing/state
and feedback. Use a narrow evaluation scope before extending to registered normal
development workspaces; exclude experiments, fixed comparisons and unattended
wake workspaces explicitly. A broad parent root includes all descendants.

From the public checkout, use `python bin/place.py necessity install
--codex-home PATH --settings FILE`, then `necessity check --codex-home PATH`.
The wheel exposes the same operations through `agent-rules necessity`.
Installation copies the fixed implementation and records its hashes alongside
the exact owned native hook definitions. It preserves unrelated hook groups and
does not write trust, feature flags, permissions, or routing. Repeating the same
install is a no-op; a changed or damaged installation is refused. To adopt changed
source, remove the intact old owned installation first, then install the new one.

Use Codex's official `/hooks` interface to inspect and trust these definitions.
Check the effective native hook list for duplicates in other config layers.
Start a new ordinary session and verify event delivery and the restricted review
round trip. A matching file check alone cannot attest trust, startup loading, or
model-visible delivery. Do not bypass hook trust for acceptance.

`python bin/place.py necessity remove --codex-home PATH` removes only unchanged
owned definitions/files. It preserves other hooks, config.toml, auth, working
files and local decision state. Modified/co-owned hook groups require resolution
before removal; do not delete the implementation while a retained definition
still calls it. Trust records are left to Codex's own interface.
`necessity status --codex-home PATH` reads bounded candidate verdicts and available
usage without printing saved prompts. A missing database means no persisted
observations, not successful native acceptance.
The separate `diagnostics` list reports failures before candidate creation using
reason code, event/tool labels, scope classification, byte boundary and a digest
reference. It contains no rejected input, image, credential or exception message.
Diagnostics use the existing database and retention period; their combined
metadata is bounded by `max_input_bytes`, evicting oldest diagnostics only. Tiny
budgets or unavailable state can prevent persistence; the hook then explicitly
reports that the diagnostic was not persisted. `diagnostics_omitted` counts
records omitted by the status output budget. A diagnostic is unassessed and is
not a candidate that can be resolved with `record`.

Installed commands bind their native event with `--event`, including when JSON
or configuration cannot be read. PostToolUse intake, observation and diagnostic
failures return nonblocking context with exit zero, preserving the already
executed tool's result delivery. This is not an approval. PreToolUse retains its
deny/unassessed behavior and all ordinary permission boundaries. Old unbound
installations remain removable through the management entry; adopt changed
source using the intact old installation's normal remove, then install/check.
After handling a delivered candidate, the execution agent can use `necessity
record --codex-home PATH --candidate ID --outcome handled|deferred|unassessed
--evidence TEXT`. This records a bounded disposition and evidence for that exact
candidate. It cannot change the original verdict, authorize a denied operation,
or create an exception; no internal JSON editing is needed.

Use the same absolute Python executable used for installation and the installing
source's `bin/place.py` for recovery. The ownership manifest pins that entry and
its management implementation. A single static invocation of `necessity --help`,
or `check`, `status`, `record`, or `remove` (including their help), adds no necessity
decision in either PreToolUse or PostToolUse. It is recognized before opening
candidate state, so missing requests, exhausted budgets, unavailable reviewers,
and unavailable state cannot prevent reaching diagnosis or removal. Commands
still validate their inputs and report real database/permission errors. This
does not fix interpreter-name mismatches in older ownership manifests.

The exemption does not cover a different entry or Python executable, installation,
other `place.py` operations, appended commands, redirections, or dynamic code.
Literal evidence is data even when it contains command examples. Reviewer
children retain their tool prohibition. Normal permissions and other hooks still
apply; no `allow` decision or input replacement is returned.

## Runtime behavior and limits

UserPromptSubmit supplies the current request automatically. A single explicitly
referenced GitHub issue/comment can be fetched through existing `gh` auth; no
whole issue/comment crawl is performed. Missing/ambiguous requests remain
unassessed. Ordinary workers without their own prompt inherit only an unambiguous
direct request in the same native session family and workspace; later parent
prompts refresh that context, and explicit worker prompts supersede it. Verdicts
and caches are not inherited. Normal tool negatives call no model. Candidate reviews return two
separate decisions: current action and normal/delete-or-reuse/disposable/
integration-proposal/unassessed disposition. An integration proposal is not
authorization to implement another feature.

The adapter never returns `allow`, edits tool input, overrides security decisions,
or replaces original PostToolUse output. Denials use native PreToolUse `deny`.
Stop requests one pass to preserve pending results; a recursive Stop reports
remaining uncertainty without forcing an infinite continuation. Resume/compact
restores pending records. The reviewer child marker denies its covered local
tools and prevents recursive review, while other native hooks remain enabled.
The CLI's read-only sandbox and approval policy also remain in force. Hosted or
specialized tool coverage is not a zero-tool or same-user tamper-proof boundary.

Review uses the existing Codex executable/auth in a neutral temporary cwd,
read-only sandbox, no approvals, no project instructions/skills/apps/plugins or
collaboration, web search disabled, and configured MCP servers explicitly disabled.
MCP names containing characters other than ASCII letters, digits, `_` or `-`
remain unassessed: the CLI's dotted override keys cannot safely encode them.
The reviewer is told to use supplied evidence only; observed tool attempts
invalidate its result. Strict structured output validates candidate identity and
both decision axes. No SDK, copied authentication, daemon or autonomous Issue
posting is involved. Return material proposals once through the existing task's
normal reporting path.

Local SQLite state contains bounded sanitized request text, hashes, outcomes and
decisions, not full transcripts or raw programs. Credential-like input prevents
external review. Redaction is conservative and is not general secret discovery.
Native transcript/agent identity separates lanes where supplied; missing native
identity limits attribution. Input/task/config/file changes invalidate reuse.
An in-flight identical candidate is not charged again; interruption leaves it
unassessed, never approved. Expired state is purged opportunistically on subsequent
events, not by a background retention service. A dormant installation can retain
state until the next event. Keep the directory private and outside Git.
Resume/compact without returned pending records explicitly leaves expired or
missing history unassessed; it is not proof that earlier candidates were handled.
Consult the existing task result for evidence outside the configured retention.
An exact static Python `--version` or `-V` query without extra arguments or
redirection is a normal selector negative, not a permission grant. Code, module
execution and unsupported interpreter syntax retain their existing assessment.
Static Python script calls in PowerShell observe both the process and script
path. They are not inline programs; running a script observed as generated or
modified in the same session still reaches candidate selection.

PostToolUse status is recorded only from structured exit status; prose is not
interpreted as a successful/failed exit. `write_stdin` cannot be certified before
input is sent. Unknown shell syntax, dynamic evaluation and paths outside the
observed workspace remain gaps. Existing build dependency trees are not scanned.

## Verification

Run `python -m unittest tests.test_necessity_select tests.test_necessity_hook
tests.test_necessity_install tests.test_necessity_review` from the checkout.
PowerShell parser behavior is tested where `pwsh` is installed and otherwise
explicitly skipped. The existing package CI also installs the optional parsers
and runs the installed-wheel setup/check/event/remove test in `test_project`.
These fixtures do not establish native trust, root/worker/resume/compact event
delivery or a real model round trip; record those separately on each target host.
