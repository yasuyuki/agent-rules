---- MODULE CodexSerenaUpdate ----
\* agent-environment runtimes/update_codex_serena.py: `apply` and `rollback`
\* run one after another on one config and one --backup path, each killed or
\* failing at any step, while another writer may change the config whenever
\* the exclusive handle is not held. Each action is one step of the code.
EXTENDS Naturals

CONSTANTS Mutation, MaxApply, MaxRollback, MaxOutside, MaxFaults

\* Config bytes. "O" is the config before any run, "E" what another writer
\* wrote, "P" torn bytes from an interrupted in-place write. Install(x) is what
\* the staged Codex writer produces from x; "I", "EI" and "PI" exist only
\* after an apply wrote them.
Content == {"O", "I", "E", "EI", "P", "PI"}
Install(x) == CASE x = "O" -> "I" [] x = "E" -> "EI" [] x = "P" -> "PI" [] OTHER -> x
Written == {"I", "EI", "PI", "P"}
Pcs == {"idle", "applyRead", "stage", "rollbackRead", "lock", "compare", "backup",
        "receipt", "write", "readback", "recover"}
Exits == {"none", "changed", "unchanged", "error", "recoveryFailed", "killed"}

VARIABLES config, backup, receipt, locked, cmd, pc, start, target, rec, wrote,
          applies, rollbacks, outside, faults, lastExit,
          clobbered, unauthorized, lieChanged, lieError

vars == <<config, backup, receipt, locked, cmd, pc, start, target, rec, wrote,
          applies, rollbacks, outside, faults, lastExit,
          clobbered, unauthorized, lieChanged, lieError>>

run == <<cmd, start, target, rec, wrote>>
counts == <<applies, rollbacks, outside, faults>>
flags == <<clobbered, unauthorized, lieChanged, lieError>>

TypeOK ==
  /\ config \in Content
  /\ backup \in Content \cup {"none", "torn"}
  /\ receipt.st \in {"none", "torn", "ok"}
  /\ locked \in BOOLEAN
  /\ cmd \in {"none", "apply", "rollback"} /\ pc \in Pcs
  /\ start \in Content \cup {"-"} /\ target \in Content \cup {"-", "none", "torn"}
  /\ rec \in Content \cup {"none"} /\ wrote \in BOOLEAN
  /\ lastExit \in Exits

Init ==
  /\ config = "O" /\ backup = "none"
  /\ receipt = [st |-> "none", orig |-> "-", inst |-> "-"]
  /\ locked = FALSE /\ cmd = "none" /\ pc = "idle"
  /\ start = "-" /\ target = "-" /\ rec = "none" /\ wrote = FALSE
  /\ applies = 0 /\ rollbacks = 0 /\ outside = 0 /\ faults = 0 /\ lastExit = "none"
  /\ clobbered = FALSE /\ unauthorized = FALSE /\ lieChanged = FALSE /\ lieError = FALSE

\* The run returns or raises; the handle closes with it.
Exit(how) == pc' = "idle" /\ locked' = FALSE /\ lastExit' = how

\* An error exit that does not say "automatic config recovery failed".
ExitError ==
  /\ Exit("error")
  /\ lieError' = (lieError \/ (wrote /\ config' # start))

Fault == faults < MaxFaults /\ faults' = faults + 1

\* main: `apply` with the same --command and --backup each time.
StartApply ==
  /\ pc = "idle" /\ applies < MaxApply
  /\ applies' = applies + 1 /\ cmd' = "apply" /\ pc' = "applyRead"
  /\ wrote' = FALSE /\ rec' = "none" /\ start' = "-" /\ target' = "-"
  /\ UNCHANGED <<config, backup, receipt, locked, rollbacks, outside, faults, lastExit, flags>>

\* main: `rollback`, with --recover-sha256 omitted or naming the bytes the user
\* just inspected. Any other hash makes rollback raise before _publish.
StartRollback ==
  /\ pc = "idle" /\ rollbacks < MaxRollback
  /\ rollbacks' = rollbacks + 1 /\ cmd' = "rollback" /\ pc' = "rollbackRead"
  /\ wrote' = FALSE /\ rec' \in {"none", config} /\ start' = "-" /\ target' = "-"
  /\ UNCHANGED <<config, backup, receipt, locked, applies, outside, faults, lastExit, flags>>

\* update: config.read_bytes, _parse and the Serena entry checks, then the
\* `desired == expected` return. Torn bytes may or may not parse.
ApplyRead ==
  /\ pc = "applyRead"
  /\ \/ config = "P" /\ ExitError /\ UNCHANGED <<start, target>>
     \/ /\ start' = config /\ target' = Install(config)
        /\ IF Install(config) = config
             THEN Exit("unchanged") /\ UNCHANGED lieError
             ELSE pc' = "stage" /\ UNCHANGED <<locked, lastExit, lieError>>
  /\ UNCHANGED <<config, backup, receipt, cmd, rec, wrote, counts,
                 clobbered, unauthorized, lieChanged>>

\* update: native_update and _validate_native on the staged copy, and the
\* comparisons of the staged bytes.
Stage ==
  /\ pc = "stage"
  /\ \/ pc' = "lock" /\ UNCHANGED <<locked, lastExit, faults, lieError>>
     \/ Fault /\ ExitError
  /\ UNCHANGED <<config, backup, receipt, run, applies, rollbacks, outside,
                 clobbered, unauthorized, lieChanged>>

\* rollback: backup.read_bytes, the receipt checks, config.read_bytes, and
\* the refusals before _publish.
RollbackRead ==
  /\ pc = "rollbackRead"
  /\ start' = config /\ target' = backup
  /\ IF ~(backup \in Content /\ receipt.st = "ok" /\ receipt.orig = backup)
       THEN ExitError
     ELSE IF config = backup
       THEN Exit("unchanged") /\ UNCHANGED lieError
     ELSE IF rec # "none" /\ rec # config
       THEN ExitError
     ELSE IF config # receipt.inst /\ rec = "none" /\ Mutation # "rollback-any-bytes"
       THEN ExitError
     ELSE pc' = "lock" /\ UNCHANGED <<locked, lastExit, lieError>>
  /\ UNCHANGED <<config, backup, receipt, cmd, rec, wrote, counts,
                 clobbered, unauthorized, lieChanged>>

\* _locked_config: CreateFileW with no sharing.
Lock ==
  /\ pc = "lock" /\ ~locked
  /\ locked' = TRUE /\ pc' = "compare"
  /\ UNCHANGED <<config, backup, receipt, run, counts, lastExit, flags>>

\* _publish: `_read_bytes(stream) != expected` under the handle.
Compare ==
  /\ pc = "compare"
  /\ IF config # start /\ Mutation # "no-compare"
       THEN ExitError
       ELSE /\ pc' = IF cmd = "apply" /\ Mutation # "backup-after-write" THEN "backup" ELSE "write"
            /\ UNCHANGED <<locked, lastExit, lieError>>
  /\ UNCHANGED <<config, backup, receipt, run, counts, clobbered, unauthorized, lieChanged>>

AfterSaveBackup == IF wrote THEN "readback" ELSE "write"

\* save_backup: _exclusive_write of the backup ("xb" refuses an existing file).
SaveBackup ==
  /\ pc = "backup"
  /\ IF backup # "none" /\ Mutation # "backup-overwrite"
       THEN /\ UNCHANGED backup
            /\ IF wrote THEN pc' = "recover" /\ UNCHANGED <<locked, lastExit, lieError>>
               ELSE ExitError
       ELSE backup' = start /\ pc' = "receipt" /\ UNCHANGED <<locked, lastExit, lieError>>
  /\ UNCHANGED <<config, receipt, run, counts, clobbered, unauthorized, lieChanged>>

\* save_backup: _exclusive_write of the receipt next to the backup.
SaveReceipt ==
  /\ pc = "receipt"
  /\ IF receipt.st # "none" /\ Mutation # "backup-overwrite"
       THEN /\ UNCHANGED receipt
            /\ IF wrote THEN pc' = "recover" /\ UNCHANGED <<locked, lastExit, lieError>>
               ELSE ExitError
       ELSE /\ receipt' = [st |-> "ok", orig |-> start, inst |-> target]
            /\ pc' = AfterSaveBackup /\ UNCHANGED <<locked, lastExit, lieError>>
  /\ UNCHANGED <<config, backup, run, counts, clobbered, unauthorized, lieChanged>>

\* _write_bytes of the new bytes: it completes, raises after a partial write,
\* or returns although the bytes on disk are not the new ones.
Write ==
  /\ pc = "write"
  /\ wrote' = TRUE
  /\ clobbered' = (clobbered \/ config # start)
  /\ unauthorized' = (unauthorized \/ (cmd = "rollback" /\ config \notin {receipt.inst, rec}))
  /\ \/ config' = target /\ pc' = "readback" /\ UNCHANGED faults
     \/ Fault /\ config' = "P" /\ pc' = "recover"
     \/ Fault /\ config' = "P" /\ pc' = "readback"
  /\ UNCHANGED <<backup, receipt, locked, cmd, start, target, rec, applies, rollbacks,
                 outside, lastExit, lieChanged, lieError>>

\* _publish: `live != data or _parse(live) != parsed`, then return.
Readback ==
  /\ pc = "readback"
  /\ IF config # target /\ Mutation # "skip-readback"
       THEN pc' = "recover" /\ UNCHANGED <<locked, lastExit, lieChanged>>
     ELSE IF cmd = "apply" /\ Mutation = "backup-after-write" /\ receipt.st = "none"
       THEN pc' = "backup" /\ UNCHANGED <<locked, lastExit, lieChanged>>
     ELSE Exit("changed") /\ lieChanged' = (lieChanged \/ config # target)
  /\ UNCHANGED <<config, backup, receipt, run, counts, clobbered, unauthorized, lieError>>

\* _publish `except BaseException`: write the starting bytes back and read them.
Recover ==
  /\ pc = "recover"
  /\ IF Mutation = "no-recovery"
       THEN UNCHANGED <<config, faults>> /\ ExitError
       ELSE \/ config' = start /\ ExitError /\ UNCHANGED faults
            \/ Fault /\ config' = "P" /\ Exit("recoveryFailed") /\ UNCHANGED lieError
  /\ UNCHANGED <<backup, receipt, run, applies, rollbacks, outside,
                 clobbered, unauthorized, lieChanged>>

\* The process dies. A write in progress leaves torn bytes behind.
Kill ==
  /\ pc \notin {"idle"}
  /\ Exit("killed")
  /\ \/ UNCHANGED <<config, backup, receipt>>
     \/ pc \in {"write", "recover"} /\ config' = "P" /\ UNCHANGED <<backup, receipt>>
     \/ pc = "backup" /\ backup = "none" /\ backup' = "torn" /\ UNCHANGED <<config, receipt>>
     \/ pc = "receipt" /\ receipt.st = "none"
        /\ receipt' = [receipt EXCEPT !.st = "torn"] /\ UNCHANGED <<config, backup>>
  /\ UNCHANGED <<run, counts, flags>>

\* Codex, the user or another tool writes the config. Windows refuses any open
\* while the handle is held.
OutsideWrite ==
  /\ ~locked \/ Mutation = "share-handle"
  /\ outside < MaxOutside /\ config # "E"
  /\ config' = "E" /\ outside' = outside + 1
  /\ UNCHANGED <<backup, receipt, locked, cmd, pc, run, applies, rollbacks, faults,
                 lastExit, flags>>

\* Every run has been made; nothing else happens.
Done ==
  /\ pc = "idle" /\ applies = MaxApply /\ rollbacks = MaxRollback
  /\ UNCHANGED vars

Next == StartApply \/ StartRollback \/ ApplyRead \/ Stage \/ RollbackRead \/ Lock
        \/ Compare \/ SaveBackup \/ SaveReceipt \/ Write \/ Readback \/ Recover
        \/ Kill \/ OutsideWrite \/ Done

Spec == Init /\ [][Next]_vars

\* The updater writes only over the bytes it read at its start and compared
\* under the handle.
NoClobber == ~clobbered

\* rollback writes only over the bytes its receipt says apply installed, or
\* over the bytes --recover-sha256 names.
RollbackAuthorized == ~unauthorized

\* Whenever the config holds bytes an apply or a failed write produced, the
\* backup holds clean bytes and a receipt names them, so rollback can restore.
OriginalRecoverable ==
  config \in Written =>
    /\ backup \in Content \ {"P"}
    /\ receipt.st = "ok" /\ receipt.orig = backup

\* "changed" means the config holds what the run meant to write.
ChangedMeansWritten == ~lieChanged

\* An ordinary error means the config is as the run found it.
ErrorMeansUntouched == ~lieError
====
