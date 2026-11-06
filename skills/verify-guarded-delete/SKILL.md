---
name: verify-guarded-delete
description: Model-check with TLA+ that agent-environment's retention/guarded_delete.py deletes only after its record reads back and that its exit code and `completed` match what it deleted, under kills, exceptions, another writer and reruns, and that a retry after a failure that deleted nothing completes. Use when a change touches preserve_and_delete, remove, conclude, save_result, run, already_completed, inspect, write_new or read_back in retention/guarded_delete.py.
license: MIT
---

# Verify guarded_delete

`retention/guarded_delete.py` in agent-environment is the only entry that agents
use to delete finished work outputs. Callers trust its exit code and
`completed`, and the record is the only evidence of what was deleted. This check
explores every order of steps in a small model of one run: the process raising
or being killed at any step, another process writing in the cleanup root, the
same command run again afterwards, and the retry that the retention rule allows
after a failure that deleted nothing: the same targets with a new record path.

## Promises

| Invariant | Promise | Harm when broken |
| --- | --- | --- |
| `NoDeleteWithoutRecord` | Nothing is deleted before the record of every target is written, read back and validated. | A file is gone with no hash or name kept. |
| `DeletesOnlyRecordedContent` | Every deleted file is the one whose hash is in the record. | Content is deleted that the record does not describe. |
| `CompletedMeansRunDeletedAll` | Exit 0 means this run deleted every target, none is present, and the result file says completed. | A caller closes the task while targets remain or were never checked. |
| `FailedMeansNothingDeleted` | Exit 1, or a saved result of `failed`, means nothing was deleted. | The retention rule lets a caller rerun after it, and a caller reports nothing lost while recorded content is gone. |
| `RetryCompletes` | After exit 1, or a saved `failed` after an interruption, the same targets with a new record complete when nothing else writes in the root. | Every failure that deleted nothing waits for the owner again (agent-environment#26). |
| `RerunZeroMeansAllDeleted` | A rerun with the same arguments reports success only when the first run deleted every target. | A killed run is reported as completed. |

`TypeOK` guards the model itself.

## Coverage

All covered code is in `retention/guarded_delete.py` of agent-environment. Each
TLA+ action is one step of it:

| Action | Code |
| --- | --- |
| `Inspect` | `preserve_and_delete`: `inspect` and `describe` of each target; a missing target raises |
| `WriteRecord`, `RecordReadsBackWrong` | `preserve_and_delete`: `write_new`, `read_back` and `validate_record` of the record |
| `Verify` | `preserve_and_delete`: the loop that inspects, compares `_identity` and hashes again after the record |
| `Check` | the deletion loop: `inspect` and the `_identity` comparison before `remove` |
| `Unlink` | `attempt.removing = entry`, then `remove`: `os.unlink` outside Windows; on Windows `CreateFileW`, the identity check on the handle, then the disposition. An `Exception` from `remove` comes before its unlink and clears `attempt.removing` |
| `Count` | `attempt.removed.append(entry)`, then `attempt.removing = None` |
| `FinalRead` | the last `read_back` of the record |
| `Fault` | any call in `preserve_and_delete` raising, or an interruption caught by `except BaseException` in `run`; between `Unlink` and `Count` only an interruption, and one inside `remove` leaves `attempt.removing` set |
| `Conclude` | `conclude`: `surely_absent`, the `len(gone) != len(attempt.removed)` and `remaining_files` checks, then `partial` when anything is gone, `attempt.removed` is not empty or `attempt.removing` is set |
| `SaveResult`, `SaveResultFails` | `save_result`: `write_new` and `read_back` of `FILE.result.json` |
| `Kill` | the process is killed; nothing after runs |
| `OutsideWrite` | another process writes a new file at a target or deletes one |
| `Rerun` | `run` finding the record, then `already_completed` |
| `Retry` | the caller, as step 3 of agent-environment's `rules/generated-artifact-retention.rule.md` allows, running `run` again with the same targets and a new record path |

Last confirmed against the code at agent-environment commit
`85ea6fb542f116ee8348b87b2f02122a4deccc23`. Move this commit forward only after
you have read every change to the covered functions since it and confirmed that
the table and the model still describe the code.

## Does a change touch it?

From the agent-environment checkout:

```sh
git diff 85ea6fb542f116ee8348b87b2f02122a4deccc23 -- retention/guarded_delete.py rules/generated-artifact-retention.rule.md
```

Read the diff for the functions in the table, and for the retry wording in step
3 of the rule, which `Retry` describes. `share`, `parse_meta`,
`load_targets`, `relative` and argument parsing in `main` are outside this check;
a change only there does not need it.

## Run

Requires Python 3.12 or later, Java 11 or later, and `tla2tools.jar` 1.7.4 from
<https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4>. The script refuses any
other jar by SHA-256. From the agent-rules checkout:

```sh
python3 -B skills/verify-guarded-delete/scripts/check.py --tla2tools /path/to/tla2tools.jar --java /path/to/java
```

`--tla2tools` and `--java` default to `$TLA2TOOLS` and `$JAVA`. The script runs
31 TLC jobs, one invariant each, in about 25 seconds, and prints one line per
job. Pass `--out <new directory>` to keep each job's `tlc.out`; without it the
outputs are deleted. It exits 0 when every job matched its expectation, 1 on any
`MISMATCH`, and 2 when the jar is missing or wrong.

Each invariant runs on POSIX and on Windows, first with no other writer
(`writers=0`, the retention rule's precondition that the root is owned and
released) and then with one write by another process (`writers=1`).

| Platform | Mutation | Invariant | Writers | Expected |
| --- | --- | --- | --- | --- |
| both | `none` | every invariant | 0 | pass |
| both | `none` | `NoDeleteWithoutRecord`, `CompletedMeansRunDeletedAll`, `FailedMeansNothingDeleted`, `RerunZeroMeansAllDeleted`, `RetryCompletes` | 1 | pass |
| windows | `none` | `DeletesOnlyRecordedContent` | 1 | pass |
| posix | `none` | `DeletesOnlyRecordedContent` | 1 | finding F1 |
| posix | `skip-readback` | `NoDeleteWithoutRecord` | 0 | violated |
| windows | `no-handle-check` | `DeletesOnlyRecordedContent` | 1 | violated |
| posix | `trust-own-count` | `CompletedMeansRunDeletedAll` | 1 | violated |
| posix | `rerun-without-result` | `RerunZeroMeansAllDeleted` | 1 | violated |
| windows | `count-from-filesystem` | `FailedMeansNothingDeleted` | 1 | violated |
| posix | `forget-removing` | `FailedMeansNothingDeleted` | 1 | violated |
| posix | `retry-same-record` | `RetryCompletes` | 0 | violated |

The mutation rows prove that each promise can fail. `skip-readback` deletes
after a record that reads back wrong. `no-handle-check` drops the identity check
on the Windows handle in `remove`. `trust-own-count` makes `conclude` trust
`attempt.removed` without looking at the filesystem. `rerun-without-result`
lets `already_completed` accept a record without a completed result file.
`count-from-filesystem` is `conclude` before the F2 fix, which looked only at
the filesystem. `forget-removing` drops `attempt.removing`, so an interruption
right after an unlink is missed. `retry-same-record` retries with the earlier
record path, which `run` refuses with 2 once that record exists; this is why the
rule says a new `--record`.

The two checks in `conclude` overlap: removing only the `len(gone)` comparison or
only the `remaining_files` check passes, because the other catches the same
runs. Only removing both breaks a promise.

## Known findings

F1 is in
[agent-environment#57](https://github.com/yasuyuki/agent-environment/issues/57)
and was reproduced on the real code. It needs another process writing in the
root during the run, which the retention rule excludes.

**F1, POSIX.** The run hashes both targets, writes and reads back the record and
hashes again. In the deletion loop `inspect` finds target `a` unchanged. Another
process replaces `a`. `remove` calls `os.unlink`, which deletes the new file.
The run exits 0 with `completed: true`, and the deleted content's hash is not
in the record. Windows opens a handle first and checks its identity, so it stops.

## Fixed finding F2

**F2, both, fixed in agent-environment `85ea6fb`.** The run deleted `a`. Another
process created `a` again. Deleting `b` raised. `conclude` saw both paths
present, so `gone` was empty and the run exited 1 as `failed`, although it had
deleted the recorded `a`. `conclude` now also counts `attempt.removed` and
`attempt.removing`. The F2 rows pass, and `count-from-filesystem` and
`forget-removing` remove each half of the fix. The fix is what makes the
retention rule's retry after exit 1 safe (agent-environment#26).

When the check finds a new product bug, add its row to `RUNS` in
`scripts/check.py` with the expectation `finding`, so that the script reports it
on every run until the fix turns the row into a `MISMATCH`. When a fix lands,
change the row to `pass` and add a mutation that removes the fix.

## Read a result

Read each violation and each passing model with the `/statechart` skill on
`GuardedDelete.tla` and `GuardedDelete.cfg`. The cfg is the POSIX model with
one outside write, so it shows F1. Set `MaxOutside = 0` in a copy to chart the
whole run with its retry. With `--out`, the raw TLC
trace is in `<out>/<platform>-<mutation>-<invariant>-w<writers>/tlc.out`.

Decide whether a violation is a product bug or a modeling error before you act:

- A product bug's path is a sequence of steps the code can take in that order.
  Confirm it on the real code: import `guarded_delete` and replace `remove` (or
  the step the path names) with a wrapper that performs the outside write or
  raises at that point, then call `run` on a temporary root and record directory
  and compare the exit code and the files that were actually unlinked with the
  record. `tests/guarded_delete_fault.py` in agent-environment injects faults
  the same way. Replay a POSIX path on Linux; Windows takes the other branch of
  `remove`.
- A modeling error is a path the code cannot take, or a `TypeOK` violation.
  Fix the model, and keep every mutation row failing.

Never weaken an invariant, add a precondition, or lower a bound to make a row
pass. Report a new product bug in agent-environment's Issues with its path in
the code's words. Do not change product code unless the user asked for that.

## Update for an intended change

When a covered function changes on purpose, change the matching action so that
each action is still one step of the new code. Add a mutation for each new guard
that a promise relies on, and expect it to violate that promise. Run the script.
Then advance the commit in **Coverage**.

## Scope

A pass covers the model with two targets, one raised exception or bad read-back
per run, one write by another process, any number of kills, one rerun, and one
retry with a new record. The fault and outside-write budgets are shared between
the run and its retry, so a retry after a fault stands for one whose cause was
fixed. It assumes:

- Identity is what `_identity` compares (device, inode, size, mtime). A rewrite
  in place that keeps all four is not modeled.
- Hashing a file is one step; a change during hashing is caught by the `fstat`
  comparison in `sha256_file` and is modeled as a change before or after it.
- Other writers act only while the run works or after it was killed, not while
  the result is being saved or after the run ended.
- A result file that is published but whose read-back fails is modeled as not
  saved.
- An `Exception` from `remove` comes before its unlink or disposition. On Windows
  `os.close` failing after a successful disposition would break this; it is not
  modeled.

It does not cover `--share` and `--draft`, argument and target-list validation,
symlink targets, Windows reparse points, hardlink refusal, the target-parent
walk, two runs racing on the same record path, fsync durability after power
loss, or a parent directory replaced by a link between `inspect` and `unlink`.
