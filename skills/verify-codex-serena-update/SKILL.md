---
name: verify-codex-serena-update
description: Model-check with TLA+ that agent-environment's runtimes/update_codex_serena.py never writes over config bytes it did not read and compare under its exclusive handle, keeps a usable backup whenever the config holds bytes it wrote, and reports `changed` or an ordinary error only when the config says so, under kills, failed writes, another writer and reruns of apply and rollback. Use when a change touches update, rollback, _publish, _write_bytes, _exclusive_write, _locked_config or _read_bytes in runtimes/update_codex_serena.py.
license: MIT
---

# Verify update_codex_serena

`runtimes/update_codex_serena.py` in agent-environment rewrites the user's live
Codex config in place. `apply` changes the Serena command, and `rollback` puts
the saved bytes back. The user trusts it to leave alone any edit that
another writer made in the meantime, and to give back the old config after any
failure. Unit tests check the orders that someone chose. This check
explores every order of steps in a small model: two `apply` runs and two
`rollback` runs on one `--backup` path, each killed or failing at any step,
and one write by another process whenever the exclusive handle is free.

## Promises

| Invariant | Promise | Harm when broken |
| --- | --- | --- |
| `NoClobber` | Every write goes over the bytes the run read at its start and compared under the handle. | An edit by Codex, the user or another tool is silently lost. |
| `RollbackAuthorized` | `rollback` writes only over the bytes its receipt says `apply` installed, or over the bytes that `--recover-sha256` names. | A rollback discards later edits that nobody inspected. |
| `OriginalRecoverable` | While the config holds bytes that an `apply` or a torn write produced, the backup holds clean bytes and a receipt names them. | The user cannot get the previous config back. |
| `ChangedMeansWritten` | `changed` means the config holds the bytes the run meant to write. | A caller relies on a config that was never installed. |
| `ErrorMeansUntouched` | An error without "automatic config recovery failed" means the config holds the bytes the run found. | A caller retries or moves on with a torn config. |

`TypeOK` guards the model itself.

## Coverage

All covered code is in `runtimes/update_codex_serena.py` of agent-environment.
Each action is one step:

| Action | Code |
| --- | --- |
| `StartApply`, `StartRollback` | `main`: `apply` with the same `--command`, or `rollback` with `--recover-sha256` omitted or naming the bytes now in the config |
| `ApplyRead` | `update`: `config.read_bytes`, `_parse`, the Serena entry checks and `if desired == expected: return False` |
| `Stage` | `update`: `native_update`, the staged `_parse` comparison and `_validate_native` on the temporary copy |
| `RollbackRead` | `rollback`: `backup.read_bytes`, the receipt checks, `config.read_bytes`, the `current == original` return and both refusals before `_publish` |
| `Lock` | `_locked_config`: `CreateFileW` with share mode 0 |
| `Compare` | `_publish`: `if _read_bytes(stream) != expected` |
| `SaveBackup`, `SaveReceipt` | `save_backup` passed as `before_write`: `_exclusive_write` of the backup, then of `<backup>.json` |
| `Write` | `_publish`: `_write_bytes(stream, data)` completing, raising after a partial write, or returning with other bytes on disk |
| `Readback` | `_publish`: `live != data or _parse(live) != parsed`, then return |
| `Recover` | `_publish` `except BaseException`: `_write_bytes(stream, expected)` and its readback, or the "automatic config recovery failed" error |
| `Kill` | the process dies; a write in progress leaves torn bytes, and a backup or receipt being written stays torn |
| `OutsideWrite` | another process writes the config while no handle is held |
| `Done` | every run has been made |

Config bytes are abstract: `O` before any run, `E` from the other writer,
`I`, `EI` and `PI` from the staged Codex writer, and `P` torn. A rollback with
a `--recover-sha256` that does not match the config raises before `_publish`,
so the model only lets it name the current bytes.

Last confirmed against the code at agent-environment commit
`c33391936effe24b98e36423ca0dd59d0e638150`. Move this commit forward only after
you have read every change to the covered functions since it and confirmed that
the table and the model still describe the code.

## Does a change touch it?

From the agent-environment checkout:

```sh
git diff c33391936effe24b98e36423ca0dd59d0e638150 -- runtimes/update_codex_serena.py
```

Read the diff for the functions in the table. A change only to the argument
parsing in `main`, the JSON-RPC exchange inside `native_update`, or the JSON
checks inside `_validate_native` does not need this check, unless it changes
whether they raise before `_publish`.

## Run

Requires Python 3.12 or later, Java 11 or later, and `tla2tools.jar` 1.7.4 from
<https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4>. The script refuses any
other jar by SHA-256. From the agent-rules checkout:

```sh
python3 -B skills/verify-codex-serena-update/scripts/check.py --tla2tools /path/to/tla2tools.jar --java /path/to/java
```

`--tla2tools` and `--java` default to `$TLA2TOOLS` and `$JAVA`. The script runs
12 TLC jobs, one invariant each, in about 10 seconds, and prints one line per
job. Pass `--out <new directory>` to keep each job's `tlc.out`; without it the
outputs are deleted. It exits 0 when every job matched its expectation, 1 on any
`MISMATCH`, and 2 when the jar is missing or wrong.

| Mutation | Invariant | Expected |
| --- | --- | --- |
| `none` | every invariant | pass |
| `no-compare` | `NoClobber` | violated |
| `share-handle` | `NoClobber` | violated |
| `rollback-any-bytes` | `RollbackAuthorized` | violated |
| `backup-after-write` | `OriginalRecoverable` | violated |
| `backup-overwrite` | `OriginalRecoverable` | violated |
| `skip-readback` | `ChangedMeansWritten` | violated |
| `no-recovery` | `ErrorMeansUntouched` | violated |

The mutation rows prove that each promise can fail. `no-compare` drops the
comparison under the handle in `_publish`. `share-handle` lets another writer
open the config while the handle is held, as a nonzero share mode would.
`rollback-any-bytes` drops the `installed_sha256` refusal in `rollback`.
`backup-after-write` saves the backup and receipt after the write.
`backup-overwrite` opens them with `wb` in place of `xb`, so that a rerun
saves torn bytes over the real backup. `skip-readback` returns without comparing
the bytes on disk. `no-recovery` raises without writing the starting bytes back.

Every row uses `MaxApply = 2`, `MaxRollback = 2`, `MaxOutside = 1` and
`MaxFaults = 2`. Two faults are needed for a failed write followed by a
failed recovery.

## Known findings

None at the sync commit. A rerun of `apply` with the same `--backup` after a
caught failure stops with `FileExistsError` before any write. That leaves the
config intact, so it breaks no promise above.

When the check finds a new product bug, add its row to `RUNS` in
`scripts/check.py` with the expectation `finding`, so that the script reports it
on every run until the fix turns the row into a `MISMATCH`. When a fix lands,
change the row to `pass` and add a mutation that removes the fix.

## Read a result

Read each violation and each passing model with the `/statechart` skill on
`CodexSerenaUpdate.tla` and `CodexSerenaUpdate.cfg`. The cfg is one `apply`,
one `rollback`, one outside write, kills and no raised faults, which fits the
chart budget. A useful view labels each state by the config ("original",
"updated", "edited elsewhere", "torn") and whether the backup and receipt are
usable. In the passing chart, "torn" is reachable only from states where the
backup is kept. With `--out`, the raw TLC trace is in
`<out>/<mutation>-<invariant>/tlc.out`.

Decide whether a violation is a product bug or a modeling error before you act:

- A product bug's path is a sequence of steps the code can take in that order.
  Confirm it on Windows with the real code. `tests/test_codex_serena_update.py`
  in agent-environment shows how to inject each step. Patch `native_update` to
  write the config for an outside write before the handle, patch
  `_write_bytes` or `_read_bytes` to fail partway, and run a subprocess that
  calls `os._exit` for a kill. Then compare the config, the backup and the
  receipt with the path. For example, `no-compare` reaches `NoClobber` by
  "apply reads the original; another writer edits the config; apply takes the
  handle and writes", and `test_concurrent_edit_and_rollback_edit_are_preserved`
  replays that path.
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

A pass covers the model above. It assumes:

- One `--backup` path is used by every run. Runs with different backup paths
  each keep their own backup and are not modeled together.
- Runs happen one after another. Two updaters at once on the same config are
  not modeled, though the share mode 0 handle refuses the second one.
- The other writer writes whole bytes once. Its own torn writes, and writes to
  the backup or receipt, are not modeled.
- Hashes stand for bytes: two different byte strings never share a SHA-256.
- Windows `CreateFileW` with share mode 0 refuses every other open while it is
  held, and the handle closes when the process dies.

It does not cover the JSON-RPC exchange and timeouts in `native_update`, what
the staged Codex writer changes beyond the compared TOML values, `_parse`
details such as bare carriage returns, the non-Windows refusal, the
writable-mapping and open-handle refusals of `CreateFileW`, or durability after
power loss beyond the `fsync` calls.
