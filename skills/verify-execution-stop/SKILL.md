---
name: verify-execution-stop
description: Model-check with TLA+ that agent-environment's hooks/execution_stop.py respects interruption, suspension and cancellation, and requires evidence for completion and repeated continuation. Use when a change touches request handling, Stop assessment, cache publication, or the verdict and transition shapes in hooks/stop_review.py.
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

`TypeOK` guards the model itself. `ended`, `userPaused` and `blockedNoTool`
record what the user did or saw independently of the cache fields.

## Coverage

The covered code is `handle` and `assess_stop` in `hooks/execution_stop.py`
of agent-environment, including `active_request`, `new_request`,
`incomplete_handoff`, `request_context`, `request_lock`, `write_request` and
`write_state`. The model includes the verdict and transition choices that
`hooks/stop_review.py` accepts in `validate` and `validate_transition`.

| Action | Code in `handle` |
| --- | --- |
| `UserGivesIssue` | UserPromptSubmit with no active request and one Issue URL: `new_request` |
| `UserPointsToOtherIssue` | transition `replace` |
| `UserChats` | UserPromptSubmit with no active request and no URL |
| `UserFollowsUp` | transition `retain` |
| `UserResumes` | transition `resume`; `resumed` only when paused and the prompt digest is new |
| `UserSwitchesTask` | transition `suspend`, or the transition call failing |
| `UserCancels` | transition `cancel` |
| `UserInterrupts` | Interrupt for the cached `turn_id` of an active request |
| `ToolRuns` | PostToolUse writing a receipt under the binding |
| `StopQuietly` | Stop with no state, a suspended request or an inactive one |
| `StopWhileInterrupted` | Stop returning the cached handoff of an interrupted request |
| `StopNoNewEvidence` | Stop after a demand with no new receipt: `incomplete_handoff` |
| `StartStopReview` | `handle` takes a cache snapshot and starts the resolver and reviewer outside the lock |
| `InterruptDuringReview` | Interrupt writes a handoff and pauses the active request under the lock |
| `DiscardStopReview` | Stop reacquires the lock, sees the cache changed and returns without publishing the assessment |
| `Reviewer*` | Stop applies a verdict from `assess_stop` if the snapshot still matches. The verdict branches include receipt and progress checks and the downgrade of `unmanaged` for managed work. |

Turn identity, session identity and the private cache path are not modeled:
the model is one session, and an event for another turn returns a notice and
changes nothing. The comments in `ExecutionStop.tla` give the line of each
branch at the sync commit.

Last confirmed against the code at agent-environment commit
`c09c5cd4cb95a06e25cf18c0b330ddd376e8354f`. Move this commit forward only after
you have read every change to the covered code since it and confirmed that the
table, the line comments and the model still describe the code.

## Does a change touch it?

From the agent-environment checkout:

```sh
git diff c09c5cd4cb95a06e25cf18c0b330ddd376e8354f -- hooks/execution_stop.py hooks/stop_review.py
```

Any change to the covered functions needs the check. In
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

`--tla2tools` and `--java` default to `$TLA2TOOLS` and `$JAVA`. Pass `--out`
with a new directory to retain the raw TLC traces. Exit 0 means every check
matched its expectation. Exit 1 means a mismatch. Exit 2 means the jar is
missing or has the wrong hash.

| Mutation | Invariant | Race | Expected |
| --- | --- | --- | --- |
| `none` | all six promises | 0 and 1 | pass |
| `stop-ignores-interrupt` | `NoDemandWhilePaused` | 0 | violated |
| `complete-without-receipts` | `NoCompleteWithoutEvidence` | 0 | violated |
| `trust-advanced` | `NoRepeatedDemandWithoutEvidence` | 0 | violated |
| `cancel-keeps-active` | `CancelledNeverContinues` | 0 | violated |
| `complete-keeps-active` | `NoHandoffAfterFinish` | 0 | violated |
| `cancel-looks-interrupted` | `EveryStopHasReason` | 0 | violated |
| `review-overwrites-interrupt` | `NoDemandWhilePaused` | 1 | violated |

The mutation rows prove that each promise can fail. `stop-ignores-interrupt`
drops the `interrupted` check at Stop. `complete-without-receipts` drops the
downgrade of `complete` when no receipt exists. `trust-advanced` accepts the
reviewer's `advanced` progress without checking that `progress_receipts` are
new receipts. `cancel-keeps-active` leaves `active` set on transition `cancel`.
`complete-keeps-active` leaves `active` set after `complete`.
`cancel-looks-interrupted` restores the mixed cancellation state and gives the
interruption branch precedence. `review-overwrites-interrupt` applies the old
assessment after the interruption has been stored.

The hook tests replay both regressions. One sends transition `cancel` after an
interruption and expects a silent Stop. The other interrupts inside the Stop
reviewer, submits a follow-up, and checks that only explicit resumption lets
Stop demand more work. The hook tests also exercise a legacy cancelled cache
and a replacement request arriving before an older review returns.
[work-records #247](https://github.com/yasuyuki/work-records/issues/247),
[work-records #256](https://github.com/yasuyuki/work-records/issues/256)

When the check finds a new product bug, add it to `FINDINGS` in
`scripts/check.py`, so that the script reports it on every run until the fix
turns the row into a `MISMATCH`. When a fix lands, remove it from `FINDINGS`
and add a mutation that removes the fix.

## Read a result

Use the `statechart` skill on `ExecutionStop.tla` with the failing run's
configuration and `ExecutionStop.map.mjs`. The raw trace is in
`<out>/<mutation>-<invariant>-race<race>/tlc.out`.

To regenerate the [diagram of the two repaired paths](ExecutionStopChart.mmd),
copy `ExecutionStop.tla`,
`ExecutionStopChart.tla`, `ExecutionStopChart.cfg` and `ExecutionStop.map.mjs`
to a scratch directory, then pass `ExecutionStopChart.tla` and
`--view ExecutionStop.map.mjs` to `statechart`. This scenario selects
cancellation, interruption during a review, the follow-up and explicit
resumption. The runner above checks the full model.

Decide whether a violation is a product bug or a modeling error before you act:

- A product bug's path is a sequence of hook events the code can receive in
  that order. Confirm it on the real code: load `hooks/execution_stop.py` as a
  module, as `tests/test_execution_stop.py` does, and call `handle` once per
  action with a temporary state directory, a `reviewer` and `transition`
  callback that return the verdict the path names, and the same `turn_id`
  within a turn. For `InterruptDuringReview`, call `handle` for the Interrupt
  from inside the reviewer callback.
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
- Codex suppresses the output of a Stop that it interrupts. The hook tests
  inject overlapping events. Native delivery and output order remain outside
  the proof.

It does not cover SessionStart output, a mismatched session or turn, the
ambiguous-URL notices, the continuation-prompt echo, the content of the
evidence sent to the reviewer, lock and filesystem failures, a crash during
publication, or two sessions sharing a cache file. The product test covers a
replacement during a review separately from the TLA+ interleavings.
