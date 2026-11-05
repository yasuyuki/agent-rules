---
name: verify-adopt-lifecycle
description: Model-check with TLA+ that agent-environment's runtimes/adopt_lifecycle.py `adopt` resumes when the same command runs again after a run that stopped at any step, and reports "adopted" only once the switch is live, its checks passed and its task is retired. Use when a change touches adopt, install, reusable, integrate, resume, delete_branch, edit, repin, reselect_exports, apply or live_checkout in runtimes/adopt_lifecycle.py.
license: MIT
---

# Verify adopt_lifecycle

`runtimes/adopt_lifecycle.py adopt --host H --revision R --request URL` in
agent-environment switches a host's live workspace-lifecycle install. It
installs R beside the current install, commits the switch in a lifecycle task,
integrates it into `main`, applies Rulesync and checks the launch. Its docstring
promises that a failed run resumes when the same command runs again. Users rely
on this whenever a kill, a pip or git error, a Rulesync refusal or a red CI run
stops the switch partway through. This check explores every place a run can
stop, followed by reruns, with at most two stops.

## Promises

| Invariant | Promise | Harm when broken |
| --- | --- | --- |
| `InstallResumes` | A rerun never fails in `install` because of what a stopped run left. | No rerun can adopt until someone deletes the leftover by hand. |
| `SwitchResumes` | A rerun never fails in the switch task because of what a stopped run left. | Same, and the task worktree holds a half-made switch. |
| `AdoptedAfterChecks` | `adopted` is reported only after adopt saw the switch commit's required checks succeed. | A switch that broke `main`'s CI is reported as adopted. |
| `AdoptedLeavesNoTask` | `adopted` is reported only after the switch task is retired and its branch deleted. | Task worktrees and branches pile up unnoticed. |
| `AdoptedIsLive` | `adopted` means `main`, the live checkout and the Rulesync outputs all name the new install, and the install exists. | Agents launch with the old install while the host reports the new one. |

`TypeOK` guards the model itself. `selfFail` records the first failure that no
outside cause produced; the two `*Resumes` invariants read it.

## Coverage

The covered code is `adopt` in `runtimes/adopt_lifecycle.py` of
agent-environment, with `live_checkout`, `install`, `reusable`, `integrate`,
`resume`, `delete_branch`, `edit`, `repin`, `reselect_exports`, `apply` and
`launch`. Each action is one step:

| Action | Code |
| --- | --- |
| `LiveCheckout` | `live_checkout`: fetch and `merge --ff-only` |
| `ReuseOld`, `ReuseInstall` | the reuse loop in `install` over `[old, *sorted(glob(version-*))]`; `reusable` skips a prefix without an interpreter |
| `HitHalfDir` | mutation `install-reuses-half-prefix` only: the loop raising on a prefix without an interpreter |
| `BuildStart`, `VenvDone`, `PipDone` | the wheel build, `python -m venv <prefix>` and the offline `pip install` in `install` |
| `Precheck` | `rulesync_states` before the switch in `adopt` |
| `Begin*`, `Subject` | `integrate`: `begin` when the worktree path is missing; when HEAD's subject is not the switch subject, `git restore --source=HEAD --staged --worktree`, then `edit` |
| `Repin`, `Grep`, `Reselect` | `edit`: `repin`, `git grep -l -F old` and its rewrites, `reselect_exports` |
| `Add`, `Commit` | `integrate`: `git add` of what `edit` returned, then commit |
| `FinishRefuses`, `Integrate`, `ChecksPass`, `ChecksFail`, `Retire`, `RetirePending` | `lifecycle finish --wait-checks --users-released` with the plan `{}`, and `integrate`'s raise on unsuccessful `integration_checks` or an unretired task |
| `FastForward`, `DeleteBranch` | `integrate`: ff of the live checkout, then `delete_branch` |
| `Resume` | `resume`, which `adopt` calls when the live checkout already names the install: `integrate` when the task worktree exists, else `delete_branch` |
| `Verify`, `Apply`, `Launch` | `adopt`'s `still selects` test, `apply`, `launch` |
| `Fault` | a kill or an outside error at any step; a kill inside `venv` leaves the prefix without an interpreter |

The model assumes, from the code: wheel builds are not byte-reproducible (two
builds of one revision gave different SHA-256), so each build gets a new
`version-<digest>` prefix; `lifecycle finish` refuses tracked changes its plan
does not cover; it integrates into `main` before it waits for the
integration checks; and a finish rerun on an integrated task waits for that
commit's checks again and then retires it (workspace-lifecycle
`tests/test_required_checks.py`). The comments in `AdoptLifecycle.tla` give the line of each
step at the sync commit.

Last confirmed against the code at agent-environment commit
`0ecadc47f39b4964c77b0e0d096384f9c6653ccf`. Move this commit forward only after
you have read every change to the covered code since it and confirmed that the
table, the line comments and the model still describe the code.

## Does a change touch it?

From the agent-environment checkout:

```sh
git diff 0ecadc47f39b4964c77b0e0d096384f9c6653ccf -- runtimes/adopt_lifecycle.py
```

A change to any function in the table needs the check. `main`, `report`,
`run`, `module_mismatches`, `renamed_only` and the `HOSTS` paths are outside it
unless they change when a step fails or what it leaves behind. A
workspace-lifecycle release that changes how `finish` treats uncovered dirty
files, or when it integrates relative to the check wait, also needs it.

## Run

Requires Python 3.12 or later, Java 11 or later, and `tla2tools.jar` 1.7.4 from
<https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4>. The script refuses any
other jar by SHA-256. From the agent-rules checkout:

```sh
python3 -B skills/verify-adopt-lifecycle/scripts/check.py --tla2tools /path/to/tla2tools.jar --java /path/to/java
```

`--tla2tools` and `--java` default to `$TLA2TOOLS` and `$JAVA`. The script runs
12 TLC jobs, one invariant each, in about 10 seconds, and prints one line per
job. Pass `--out <new directory>` to keep each job's `tlc.out`; without it the
outputs are deleted. It exits 0 when every job matched its expectation, 1 on any
`MISMATCH`, and 2 when the jar is missing or wrong.

| Mutation | Invariant | Expected |
| --- | --- | --- |
| `none` | every invariant | pass |
| `install-reuses-half-prefix` | `InstallResumes` | violated |
| `edit-without-restore` | `SwitchResumes` | violated |
| `rerun-skips-task` | `AdoptedAfterChecks`, `AdoptedLeavesNoTask` | violated |
| `pending-retire-adopts` | `AdoptedLeavesNoTask` | violated |
| `apply-trusts-precheck` | `AdoptedIsLive` | violated |
| `ignore-checks` | `AdoptedAfterChecks` | violated |

Each mutation removes one guard. `install-reuses-half-prefix` lets the reuse
loop raise on a prefix without an interpreter. `edit-without-restore` drops
the restore before `edit`. `rerun-skips-task` makes `adopt` skip `resume`.
`pending-retire-adopts` drops the raise on an unretired task.
`apply-trusts-precheck` skips `apply` for configurations that checked true
before the switch. `ignore-checks` drops the raise on unsuccessful
`integration_checks`. `tests/test_adopt_lifecycle.py` in agent-environment
fails when the real code loses any of the first four guards.

## Findings

None is open. agent-environment#58, #59 and #60 were found by this check and
fixed in `0ecadc4`; the first four mutations above remove those fixes.

When the check finds a new product bug, add it to `FINDINGS` in
`scripts/check.py`, so that the script reports it on every run until the fix
turns the row into a `MISMATCH`. When a fix lands, remove it from `FINDINGS`,
make the matching action describe the fixed code, and add a mutation that
removes the fix.

## Read a result

Read each violation and each passing model with the `/statechart` skill on
`AdoptLifecycle.tla` and `AdoptLifecycle.cfg`. The cfg allows one stop so the
whole graph fits the chart budget. With `--out`, the
raw TLC trace is in `<out>/<mutation>-<invariant>/tlc.out`.

Decide whether a violation is a product bug or a modeling error before you act:

- A product bug's path is a sequence of steps the code takes in that order.
  Confirm it on the real code: load `runtimes/adopt_lifecycle.py` as a module,
  as `tests/test_adopt_lifecycle.py` does, and call the functions the path
  names in a temporary directory. Stub only what touches the host's live
  installs, Rulesync outputs or remotes, and make the stub leave exactly what
  the path says the stopped step left.
- A modeling error is a path the code cannot take, or a `TypeOK` violation.
  Fix the model, and keep every mutation row failing.

Never weaken an invariant, add a precondition, or lower `MAX_FAULTS` to make a
row pass. Report a new product bug in agent-environment's Issues with its path
in the code's words. Do not change product code unless the user asked for that.

## Update for an intended change

When covered code changes on purpose, change the matching action so that each
action is still one step of the new code, and update its line comment. Add a
mutation for each new guard that a promise relies on, and expect it to violate
that promise. Run the script. Then advance the commit in **Coverage**.

## Scope

A pass covers the model with one host, one revision, at most two stops in
total, and three representative files (the runtime binding, one `git grep`
file, one export declaration). It assumes:

- Only this adopt run changes the task worktree, the live checkout and
  `main`; one host adopts at a time, as the docstring requires.
- `lifecycle begin` and `finish` are atomic apart from the stop between
  integration and the check wait, and between the wait and retire. Their own
  crash recovery is workspace-lifecycle's.
- One `apply` makes the Rulesync outputs match; the Rulesync transaction is
  checked by verify-rulesync-transaction.

It does not cover the `edit` command alone, wheel and module contents, the
`renamed_only` export test, `launch`'s choice between `--explain` and the smoke
launch, two hosts adopting at once, or a rerun with a different `--revision`.
