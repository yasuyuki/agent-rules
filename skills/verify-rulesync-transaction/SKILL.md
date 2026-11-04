---
name: verify-rulesync-transaction
description: Model-check the crash, rollback and recovery transaction of the agent-rules Rulesync adapter with TLA+. Use when a change touches apply, _recover, _validate_reconcile, _plan, _apply_reconcile, _write_atomic or _restore in bin/rulesync_backend.py, or the journal and ownership manifest they write.
license: MIT
---

# Verify the Rulesync transaction

`agent-rules apply` rewrites files that agents load, such as `AGENTS.md` and
`.claude/skills/<id>/SKILL.md`, next to files the user wrote by hand. The process
can be killed at any point. This check explores every order of filesystem calls
in a small model of one output tree and reports any order that breaks a promise.

## Promises

| Invariant | Promise | Harm when broken |
| --- | --- | --- |
| `NoClobber` | Apply never replaces or deletes a file that it did not write. | A user's hand-written rule or skill is lost. |
| `AllOrNothing` | With no apply running and no journal pending, every output and `.rulesync-ownership.json` is entirely before or entirely after the last transaction. | Agents load a half-updated rule set and the manifest disowns or claims the wrong files. |
| `NoStuck` | A crash alone never leaves apply refusing until someone repairs the output by hand. | Every later apply fails and the user must find and delete a stray file. |

`TypeOK` guards the model itself.

## Coverage

All covered code is in `bin/rulesync_backend.py`. Each TLA+ action models one call:

| Action | Code |
| --- | --- |
| `StartApply` | `apply`: `_output_lock`, then `_recover` only when `.rulesync-transaction.json` exists |
| `RecoverCheck` | `_recover`: refuse when a journaled path holds neither its before nor its after bytes |
| `RecoverRestore`, `RecoverReplace` | `_recover` calling `_restore` |
| `RecoverRmdir`, `RecoverDone` | `_recover`: `rmdir` of journaled directories, then unlink of the journal |
| `Validate` | `_validate_reconcile` refusals (externally modified owned file, unowned file would be replaced, unowned same-name skill), `_plan`, and the journal `_write_atomic` |
| `Mkdir`, `UnlinkStale`, `WriteFile`, `ApplyReplace`, `WriteManifest`, `Commit` | the `try` block of `_apply_reconcile` |
| `WriteFile` then `ApplyReplace` | `_write_atomic`: `tempfile.mkstemp` beside the target, then `os.replace` |
| `Fault`, `RollbackRestore`, `RollbackReplace`, `RollbackRmdir`, `RollbackDone` | the `except` block of `_apply_reconcile` |
| `Crash` | the process is killed; no `finally` runs |
| `UserEdit` | the user writes or deletes an output while no apply runs |

Last confirmed against the code at commit
`daab169173fdc3bbbc8f2c5e52251b00310ba5e0`. Move this commit forward only after
you have read every change to the covered functions since it and confirmed that
the table and the model still describe the code.

## Does a change touch it?

From the agent-rules checkout:

```sh
git diff daab169173fdc3bbbc8f2c5e52251b00310ba5e0 -- bin/rulesync_backend.py
```

Read the diff for the functions in the table, `MANIFEST`, `JOURNAL` and `LOCK`.
A change elsewhere in the file, such as generation or config loading, does not
need this check.

## Run

Requires Python 3.12 or later, Java 11 or later, and `tla2tools.jar` 1.7.4 from
<https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4>. The script refuses any
other jar by SHA-256. From the agent-rules checkout on Linux:

```sh
python3 -B skills/verify-rulesync-transaction/scripts/check.py --tla2tools /path/to/tla2tools.jar --java java
```

On the Windows controller, in PowerShell:

```console
& "C:/Users/flame/AppData/Local/Programs/Python/Python314/python.exe" -B skills/verify-rulesync-transaction/scripts/check.py --tla2tools "C:/Users/flame/AppData/Local/tlaplus/1.7.4/tla2tools.jar" --java "C:/Program Files/Microsoft/jdk-25.0.5.21-hotspot/bin/java.exe"
```

The script runs seven TLC jobs, one invariant each, in about 10 seconds. It prints
one line per job. Pass `--out <new directory>` to keep each job's `tlc.out`;
without it the outputs are deleted after the run. It exits 0
when every job matched its expectation, 1 on any `MISMATCH`, and 2 when the jar
is missing or wrong.

| Mutation | Invariant | Expected |
| --- | --- | --- |
| `none` | `NoClobber` | pass |
| `none` | `AllOrNothing` | pass |
| `none` | `NoStuck` | violated, known finding F1 |
| `skip-unowned-check` | `NoClobber` | violated |
| `recover-skip-conflict` | `NoClobber` | violated |
| `no-journal` | `AllOrNothing` | violated |
| `proposed-temp-cleanup` | `NoStuck` | pass |

The `none` rows check the current code. The mutation rows prove that each
promise can fail. `skip-unowned-check` drops the "unowned file would be replaced"
refusal. `recover-skip-conflict` drops the before-or-after check in `_recover`.
`no-journal` never writes the journal. `proposed-temp-cleanup` is the smallest
fix for F1 (`_recover` deletes the `.<name>.rulesync-tmp-*` files beside the
journaled paths) and shows that the model passes once it exists.

## Known finding F1

`NoStuck` fails on the current code, tracked in
[agent-rules#78](https://github.com/yasuyuki/agent-rules/issues/78). TLC's
shortest path:

1. Apply adds a new skill. It creates `.claude/skills/<id>/` and calls
   `_write_atomic`, which creates `.SKILL.md.rulesync-tmp-*` there.
2. The process is killed before `os.replace`.
3. The next apply runs `_recover`. It restores the backups, then calls
   `rmdir` on the new skill directory. The temporary file keeps it non-empty,
   so apply fails with `invalid Rulesync transaction` on every run.

When the killed write was updating an existing skill, the next apply instead
fails with `unowned same-name skill`. Both were reproduced on the real code by
killing a child process inside `os.replace`. The user recovers by deleting the
temporary file. When F1 is fixed, the `none`/`NoStuck` row reports `MISMATCH`
because it now passes. Change its expectation to `pass` in `scripts/check.py`.

## Read a result

Read each violation and each passing model with the `/statechart` skill on
`RulesyncTransaction.tla` and `RulesyncTransaction.cfg`. It gives the shortest
path to each broken invariant in plain words and charts the passing states.
With `--out`, the raw TLC trace is in `<out>/<mutation>-<invariant>/tlc.out`.

Decide whether a violation is a product bug or a modeling error before you act:

- A product bug's path is a sequence of calls the code can actually make in that
  order. Confirm it by forcing that order on the real code. Kill a child process
  at the named call with `os._exit`, as `test_hard_exit_transaction_recovers_before_retry`
  in `tests/test_rulesync_backend.py` does, and run `apply` again.
- A modeling error is a path the code cannot take, or a `TypeOK` violation.
  Fix the model, and keep every mutation row failing.

Never weaken an invariant, add a precondition, or lower a bound to make a row
pass. Report a new product bug with its path in the code's words. Do not change
product code unless the user asked for that.

## Update for an intended change

When a covered function changes on purpose, change the matching action so that
each action is still one call in the new code. Add a mutation for each new guard
that a promise relies on, and expect it to violate that promise. Run the script.
Then advance the commit in **Coverage**.

## Scope

A pass covers the model with 2 crashes, 1 in-process exception and 1 user edit
per behavior, two output paths (a root rule file and one skill's `SKILL.md`),
and every combination of owned, unowned, desired and stale for them.
It assumes:

- Only one apply runs at a time, as `_output_lock` enforces.
- The user does not edit outputs while an apply is running. An edit between
  `_validate_reconcile` and the write it permits can still be overwritten.
- `os.replace`, `unlink`, `mkdir` and `rmdir` are atomic.

It does not cover `check`, `preview`, `handover`, the skill directory identity
records and retirement, abandoned agy trees, links and junctions, file modes,
Grok's `CLAUDE.md` refusal, temporary files left at the output root (they block
nothing), fsync durability after power loss, or Rulesync generation.
