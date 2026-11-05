---
name: verify-execution-stop
description: Model-check with TLA+ that agent-environment's hooks/execution_stop.py never tells the agent to keep working on a request the user interrupted, switched away from or cancelled, never completes one without a tool observation, and never repeats a demand without new evidence, over every order of hook events. Use when a change touches handle, active_request, new_request, incomplete_handoff, request_context or write_state in hooks/execution_stop.py, or the verdict and transition shapes in hooks/stop_review.py.
license: MIT
---

# Verify execution_stop

`hooks/execution_stop.py` in agent-environment runs on Codex SessionStart,
UserPromptSubmit, PostToolUse, Stop and Interrupt. At Stop it can return
`decision: block`, which makes the agent keep working, or an incomplete
handoff. Users rely on it to push unfinished authorized work forward, and to
leave interrupted, suspended and cancelled work alone. This check explores
every order of hook events for one session: prompts that the classifier reads
as a new Issue, a follow-up, a resumption, another request or a cancel; tool
runs; interrupts; and every Stop reviewer verdict. With `race=1` it also lets
one Interrupt land while a Stop's reviewer runs.

## Promises

| Invariant | Promise | Harm when broken |
| --- | --- | --- |
| `NoDemandWhilePaused` | After the user interrupts or switches to another request, the hook never demands more work until the user resumes or starts a new request. | The agent resumes work the user stopped. |
| `NoCompleteWithoutEvidence` | A request never ends as complete unless some tool observation backs it. | Unverified work is closed as done. |
| `NoRepeatedDemandWithoutEvidence` | Two demands never come back to back without a tool run or a fresh resumption between them. | The agent loops on demands without doing anything. |
| `CancelledNeverContinues` | A cancelled request is never told to keep working. | The agent works on something the user cancelled. |
| `NoHandoffAfterFinish` | A request that is complete, cancelled or judged unmanaged is never handed off as unfinished. | The user is told finished work is incomplete. |
| `EveryStopHasReason` | Every stop the hook shows says why it stopped. | The user sees "remains unverified" with no reason. |

`TypeOK` guards the model itself. `ended`, `userPaused`, `blockedNoTool` and
`lost` are ghost variables: they record what the user did or saw, not what the
cache holds, so a promise is not judged by the code's own flags.

## Coverage

The covered code is `handle` in `hooks/execution_stop.py` of agent-environment,
with `active_request`, `new_request`, `incomplete_handoff`, `request_context`
and `write_state`. The reviewer and the transition classifier in
`hooks/stop_review.py` are free choices: the model allows every verdict that
`validate` and `validate_transition` accept. Each action is one hook
event on one branch:

| Action | Code in `handle` |
| --- | --- |
| `UserGivesIssue` | UserPromptSubmit with no active request and one Issue URL: `new_request` |
| `UserPointsToOtherIssue` | transition `replace` |
| `UserChats` | UserPromptSubmit with no active request and no URL |
| `UserFollowsUp` | transition `retain` |
| `UserResumes` | transition `resume`; `resumed` only when paused and the prompt digest is new |
| `UserSwitchesTask` | transition `suspend`, or the transition call failing |
| `UserCancels` | transition `cancel` |
| `UserInterrupts` | Interrupt for the cached `turn_id` |
| `ToolRuns` | PostToolUse writing a receipt under the binding |
| `StopQuietly` | Stop with no state, a suspended request or an inactive one |
| `StopWhileInterrupted` | Stop returning the cached handoff of an interrupted request |
| `StopNoNewEvidence` | Stop after a demand with no new receipt: `incomplete_handoff` |
| `Reviewer*` | Stop running the resolver and reviewer, then the verdict branches: the no-receipt downgrade of `complete`, the managed downgrade of `unmanaged`, the progress test before `decision: block`, `stopped` with `cancel` or `blocked`, and `complete` or `unmanaged` |
| `Assess` with `lost` | an Interrupt writing the cache while the reviewer runs; the Stop then writes back its own copy |

Turn identity, session identity and the private cache path are not modeled:
the model is one session, and an event for another turn returns a notice and
changes nothing. The comments in `ExecutionStop.tla` give the line of each
branch at the sync commit.

Last confirmed against the code at agent-environment commit
`f9ae1516a692602c416af77ff428dbdbb330fb41`. Move this commit forward only after
you have read every change to the covered code since it and confirmed that the
table, the line comments and the model still describe the code.

## Does a change touch it?

From the agent-environment checkout:

```sh
git diff f9ae1516a692602c416af77ff428dbdbb330fb41 -- hooks/execution_stop.py hooks/stop_review.py
```

Any change to `handle` or the helpers in the table needs the check. In
`stop_review.py` only a change to the allowed statuses, progress values,
`stop_kind` or transition actions does; prompts, the Codex call and output
parsing are outside it. `resolve_contract` and `main` are outside it too,
except that `main` turns any failure into a notice without writing the cache.

## Run

Requires Python 3.12 or later, Java 11 or later, and `tla2tools.jar` 1.7.4 from
<https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4>. The script refuses any
other jar by SHA-256. From the agent-rules checkout:

```sh
python3 -B skills/verify-execution-stop/scripts/check.py --tla2tools /path/to/tla2tools.jar --java /path/to/java
```

`--tla2tools` and `--java` default to `$TLA2TOOLS` and `$JAVA`. The script runs
17 TLC jobs, one invariant each, in about 15 seconds, and prints one line per
job. Pass `--out <new directory>` to keep each job's `tlc.out`; without it the
outputs are deleted. It exits 0 when every job matched its expectation, 1 on any
`MISMATCH`, and 2 when the jar is missing or wrong.

| Mutation | Invariant | Race | Expected |
| --- | --- | --- | --- |
| `none` | every invariant except `EveryStopHasReason` | 0 | pass |
| `none` | `EveryStopHasReason` | 0 and 1 | finding #247 |
| `none` | `NoDemandWhilePaused` | 1 | finding #256 |
| `none` | the other four | 1 | pass |
| `stop-ignores-interrupt` | `NoDemandWhilePaused` | 0 | violated |
| `complete-without-receipts` | `NoCompleteWithoutEvidence` | 0 | violated |
| `trust-advanced` | `NoRepeatedDemandWithoutEvidence` | 0 | violated |
| `cancel-keeps-active` | `CancelledNeverContinues` | 0 | violated |
| `complete-keeps-active` | `NoHandoffAfterFinish` | 0 | violated |

The mutation rows prove that each promise can fail. `stop-ignores-interrupt`
drops the `interrupted` check at Stop. `complete-without-receipts` drops the
downgrade of `complete` when no receipt exists. `trust-advanced` accepts the
reviewer's `advanced` progress without checking that `progress_receipts` are
new receipts. `cancel-keeps-active` leaves `active` set on transition `cancel`.
`complete-keeps-active` leaves `active` set after `complete`.
`EveryStopHasReason` fails on the current code, which is its proof.

## Known findings

Both were reproduced by calling `handle` directly.

**#247, any timing.** In
[work-records#247](https://github.com/yasuyuki/work-records/issues/247). The
user binds an Issue, then sends a prompt that the classifier reads as `cancel`.
That branch sets `active=False`, `interrupted=True` and `handoff=''`. The Stop
of that turn checks `interrupted` before `active_request`, so it returns
`continue: false` with an empty `stopReason` and "Execution request remains
unverified."

**#256, an Interrupt during the Stop review.** In
[work-records#256](https://github.com/yasuyuki/work-records/issues/256). The
Stop reads the cache and waits for the resolver and reviewer. An Interrupt for
the same turn writes `interrupted=True`. The Stop then writes back its own
copy, with `interrupted=False`. On the next turn a follow-up gets the active
request context, a tool runs, and the Stop returns `decision: block`. Whether
Codex starts the Interrupt hook while a Stop hook process still runs is not
confirmed; if Codex kills the Stop hook, this path cannot occur.

When the check finds a new product bug, add it to `FINDINGS` in
`scripts/check.py`, so that the script reports it on every run until the fix
turns the row into a `MISMATCH`. When a fix lands, remove it from `FINDINGS`
and add a mutation that removes the fix.

## Read a result

Read each violation and each passing model with the `/statechart` skill on
`ExecutionStop.tla` and `ExecutionStop.cfg`. The cfg has `Race = 0` and one
resumption prompt so the whole graph fits the chart budget; it shows #247. Set
`Race = 1` in a copy to see #256; that model is above the budget, so the chart
draws only the bug paths. With `--out`, the raw TLC trace is in
`<out>/<mutation>-<invariant>-race<race>/tlc.out`.

Decide whether a violation is a product bug or a modeling error before you act:

- A product bug's path is a sequence of hook events the code can receive in
  that order. Confirm it on the real code: load `hooks/execution_stop.py` as a
  module, as `tests/test_execution_stop.py` does, and call `handle` once per
  action with a temporary state directory, a `reviewer` and `transition`
  callback that return the verdict the path names, and the same `turn_id`
  within a turn. For a `lost` step, call `handle` for the Interrupt from inside
  the reviewer callback.
- A modeling error is a path the code cannot take, or a `TypeOK` violation.
  Fix the model, and keep every mutation row failing.

Never weaken an invariant, add a precondition, or lower a bound to make a row
pass. Report a new product bug in work-records' Issues, where the existing
execution_stop findings are, with its path in the code's words. Do not change
product code unless the user asked for that.

## Update for an intended change

When covered code changes on purpose, change the matching action so that each
action is still one branch of the new code, and update its line comment. Add a
mutation for each new guard that a promise relies on, and expect it to violate
that promise. Run the script. Then advance the commit in **Coverage**.

## Scope

A pass covers the model with two distinct resumption prompts, any number of
events, and at most one Interrupt during a Stop review. It assumes:

- Hook events of one session arrive one at a time, except the modeled Interrupt
  during a Stop review. PostToolUse hooks that overlap write separate receipt
  files and do not write the cache.
- The classifier returns one of its five actions, and a failure is `suspend`.
  A `replace` names a new candidate URL.
- A Stop that the user interrupts does not show its output.

It does not cover SessionStart output, a mismatched session or turn, the
ambiguous-URL notices, the continuation-prompt echo, the content of the
evidence sent to the reviewer, timeouts in `main`, a crash between two cache
writes, or two sessions sharing a cache file.
