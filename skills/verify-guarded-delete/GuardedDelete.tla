---- MODULE GuardedDelete ----
\* One run of agent-environment retention/guarded_delete.py over two targets,
\* the process being killed or raising at any step, another writer in the root,
\* a later run with the same arguments, and the caller's retry with a new record
\* after a run that deleted nothing. Each action is one step of the code.
EXTENDS Naturals, FiniteSets

CONSTANTS Mutation, Windows, MaxOutside, MaxFaults

T == {1, 2}
N == 2
Running == {"inspect", "writeRecord", "verify", "check", "unlink", "count", "finalRead"}

VARIABLES pc, i, file, nextVer, seen, record, deleted, removed, removing, err, interrupted,
          status, code, exitCode, resultDisk, faults, outside, rerunExit, retried

vars == <<pc, i, file, nextVer, seen, record, deleted, removed, removing, err, interrupted,
          status, code, exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* file[t] is the identity of what is at target t, 0 when absent.
\* deleted holds <<t, identity>> for each file this run unlinked.
TypeOK ==
  /\ pc \in Running \cup {"conclude", "saveResult", "done", "killed"}
  /\ i \in 1..N
  /\ file \in [T -> 0..nextVer] /\ seen \in [T -> 0..nextVer]
  /\ record \in {"none", "bad", "good"}
  /\ deleted \subseteq (T \X (1..nextVer)) /\ removed \in 0..N
  /\ removing \in BOOLEAN /\ err \in BOOLEAN /\ interrupted \in BOOLEAN
  /\ status \in {"none", "completed", "partial", "failed"}
  /\ code \in {"none", "0", "1", "3"}
  /\ exitCode \in {"none", "0", "1", "2", "3", "raised"}
  /\ resultDisk \in {"none", "completed", "partial", "failed"}
  /\ rerunExit \in {"none", "0", "2"}
  /\ retried \in BOOLEAN

Init ==
  /\ pc = "inspect" /\ i = 1
  /\ file = [t \in T |-> t] /\ nextVer = N + 1 /\ seen = [t \in T |-> 0]
  /\ record = "none" /\ deleted = {} /\ removed = 0 /\ removing = FALSE
  /\ err = FALSE /\ interrupted = FALSE
  /\ status = "none" /\ code = "none" /\ exitCode = "none" /\ resultDisk = "none"
  /\ faults = 0 /\ outside = 0 /\ rerunExit = "none" /\ retried = FALSE

Fail == err' = TRUE /\ pc' = "conclude"

Next1(after) == IF i < N THEN i' = i + 1 /\ pc' = pc ELSE i' = 1 /\ pc' = after

\* preserve_and_delete: inspect then describe each target; a missing target raises.
Inspect ==
  /\ pc = "inspect"
  /\ IF file[i] = 0
       THEN Fail /\ UNCHANGED <<i, seen>>
       ELSE seen' = [seen EXCEPT ![i] = file[i]] /\ Next1("writeRecord") /\ UNCHANGED err
  /\ UNCHANGED <<file, nextVer, record, deleted, removed, removing, interrupted, status, code,
                 exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* write_new, read_back and validate_record of the record.
WriteRecord ==
  /\ pc = "writeRecord"
  /\ record' = "good" /\ pc' = "verify"
  /\ UNCHANGED <<i, file, nextVer, seen, deleted, removed, removing, err, interrupted, status,
                 code, exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* write_new published a record that read_back finds different.
RecordReadsBackWrong ==
  /\ pc = "writeRecord" /\ faults < MaxFaults
  /\ record' = "bad" /\ faults' = faults + 1
  /\ IF Mutation = "skip-readback" THEN pc' = "verify" /\ UNCHANGED err ELSE Fail
  /\ UNCHANGED <<i, file, nextVer, seen, deleted, removed, removing, interrupted, status, code,
                 exitCode, resultDisk, outside, rerunExit, retried>>

\* The loop after the record: inspect again, compare identity, hash again.
Verify ==
  /\ pc = "verify"
  /\ IF file[i] # seen[i] THEN Fail /\ UNCHANGED i ELSE Next1("check") /\ UNCHANGED err
  /\ UNCHANGED <<file, nextVer, seen, record, deleted, removed, removing, interrupted, status,
                 code, exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* Deletion loop: inspect and compare identity with the first inspection.
Check ==
  /\ pc = "check"
  /\ IF file[i] # seen[i] THEN Fail ELSE pc' = "unlink" /\ UNCHANGED err
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, removing, interrupted,
                 status, code, exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* attempt.removing = entry, then remove(): os.unlink(path) outside Windows; on
\* Windows a handle opened by path, whose identity is compared with the first
\* inspection before it is deleted. A Stop or OSError from remove() comes before
\* the unlink and clears attempt.removing.
Unlink ==
  /\ pc = "unlink"
  /\ IF file[i] = 0
          \/ (Windows /\ Mutation # "no-handle-check" /\ file[i] # seen[i])
       THEN Fail /\ UNCHANGED <<file, deleted, removing>>
       ELSE /\ deleted' = deleted \cup {<<i, file[i]>>}
            /\ file' = [file EXCEPT ![i] = 0]
            /\ removing' = TRUE
            /\ pc' = "count"
            /\ UNCHANGED err
  /\ UNCHANGED <<i, nextVer, seen, record, removed, interrupted, status, code, exitCode,
                 resultDisk, faults, outside, rerunExit, retried>>

\* attempt.removed.append(entry), then attempt.removing = None.
Count ==
  /\ pc = "count"
  /\ removed' = removed + 1 /\ removing' = FALSE
  /\ IF i < N THEN i' = i + 1 /\ pc' = "check" ELSE i' = 1 /\ pc' = "finalRead"
  /\ UNCHANGED <<file, nextVer, seen, record, deleted, err, interrupted, status, code, exitCode,
                 resultDisk, faults, outside, rerunExit, retried>>

\* The final read_back of the record succeeds; its failure is a Fault.
FinalRead ==
  /\ pc = "finalRead" /\ pc' = "conclude"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, removing, err, interrupted,
                 status, code, exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* Any call in preserve_and_delete raises: an OSError, a Stop, or an interruption
\* that run() catches as BaseException. Between remove() returning and the count
\* only an interruption can land. An interruption inside remove() leaves
\* attempt.removing set, because the except clause catches only Exception.
Fault ==
  /\ pc \in Running /\ faults < MaxFaults
  /\ faults' = faults + 1
  /\ \E stop \in (IF pc = "count" THEN {TRUE} ELSE BOOLEAN) :
       /\ interrupted' = stop
       /\ removing' = (removing \/ (stop /\ pc = "unlink"))
  /\ Fail
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, status, code, exitCode,
                 resultDisk, outside, rerunExit, retried>>

\* conclude(): only targets in a validated record count as gone; a failed run is
\* partial when anything is gone, or this run unlinked or was cut off inside remove().
Recorded == record = "good"
Gone == {t \in T : Recorded /\ file[t] = 0}
Touched ==
  CASE Mutation = "count-from-filesystem" -> Gone # {}
    [] Mutation = "forget-removing"       -> Gone # {} \/ removed > 0
    [] OTHER                              -> Gone # {} \/ removed > 0 \/ removing
Conclude ==
  /\ pc = "conclude"
  /\ LET checked == Recorded /\ Mutation # "trust-own-count"
         bad == err \/ (checked /\ Cardinality(Gone) # removed) \/ (checked /\ Gone # T) \/ ~Recorded
     IN IF bad
          THEN IF Touched THEN status' = "partial" /\ code' = "3"
                          ELSE status' = "failed" /\ code' = "1"
          ELSE status' = "completed" /\ code' = "0"
  /\ pc' = "saveResult"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, removing, err, interrupted,
                 exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* save_result(): write_new and read_back of FILE.result.json, then the exit code;
\* an interruption is raised again after the result is saved.
Exit(c) == exitCode' = IF interrupted THEN "raised" ELSE c
SaveResult ==
  /\ pc = "saveResult"
  /\ resultDisk' = status /\ Exit(code) /\ pc' = "done"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, removing, err, interrupted,
                 status, code, faults, outside, rerunExit, retried>>

SaveResultFails ==
  /\ pc = "saveResult" /\ faults < MaxFaults
  /\ faults' = faults + 1
  /\ Exit(IF status = "completed" THEN "3" ELSE code) /\ pc' = "done"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, removing, err, interrupted,
                 status, code, resultDisk, outside, rerunExit, retried>>

\* The process is killed; nothing after this runs.
Kill ==
  /\ pc \notin {"done", "killed"}
  /\ pc' = "killed"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, removing, err, interrupted,
                 status, code, exitCode, resultDisk, faults, outside, rerunExit, retried>>

\* Another process writes a new file at a target, or deletes one, while the run
\* works or after it was killed.
OutsideWrite ==
  /\ outside < MaxOutside /\ pc \notin {"saveResult", "done"}
  /\ \E t \in T :
       \/ file' = [file EXCEPT ![t] = nextVer] /\ nextVer' = nextVer + 1
       \/ file[t] # 0 /\ file' = [file EXCEPT ![t] = 0] /\ UNCHANGED nextVer
  /\ outside' = outside + 1
  /\ UNCHANGED <<pc, i, seen, record, deleted, removed, removing, err, interrupted, status, code,
                 exitCode, resultDisk, faults, rerunExit, retried>>

\* already_completed(): the same arguments again once a record exists.
Rerun ==
  /\ pc \in {"done", "killed"} /\ record # "none" /\ rerunExit = "none"
  /\ rerunExit' =
       IF record = "good" /\ \A t \in T : file[t] = 0
          /\ (resultDisk = "completed" \/ Mutation = "rerun-without-result")
       THEN "0" ELSE "2"
  /\ UNCHANGED <<pc, i, file, nextVer, seen, record, deleted, removed, removing, err,
                 interrupted, status, code, exitCode, resultDisk, faults, outside, retried>>

\* The retention rule's recovery: after exit 1, or an interruption whose saved
\* result is failed, the caller runs the same targets once more with a new
\* record path. Fault and outside-write budgets are shared with the first run, so
\* a retry after a fault stands for one whose cause was fixed. With the old record
\* path, run() finds the earlier record and already_completed refuses with 2.
NothingDeletedReported == exitCode = "1" \/ (exitCode = "raised" /\ resultDisk = "failed")
Retry ==
  /\ pc = "done" /\ ~retried /\ NothingDeletedReported
  /\ retried' = TRUE
  /\ IF Mutation = "retry-same-record" /\ record # "none"
       THEN /\ exitCode' = "2" /\ rerunExit' = rerunExit
            /\ UNCHANGED <<pc, i, seen, record, deleted, removed, removing, err, interrupted,
                           status, code, resultDisk>>
       ELSE /\ pc' = "inspect" /\ i' = 1 /\ seen' = [t \in T |-> 0] /\ record' = "none"
            /\ deleted' = {} /\ removed' = 0 /\ removing' = FALSE
            /\ err' = FALSE /\ interrupted' = FALSE
            /\ status' = "none" /\ code' = "none" /\ exitCode' = "none" /\ resultDisk' = "none"
            /\ rerunExit' = "none"
  /\ UNCHANGED <<file, nextVer, faults, outside>>

Finished == pc \in {"done", "killed"} /\ UNCHANGED vars

Next == Inspect \/ WriteRecord \/ RecordReadsBackWrong \/ Verify \/ Check \/ Unlink \/ Count
        \/ FinalRead \/ Fault \/ Conclude \/ SaveResult \/ SaveResultFails \/ Kill
        \/ OutsideWrite \/ Rerun \/ Retry \/ Finished

Spec == Init /\ [][Next]_vars

\* Nothing is deleted before the record of every target reads back valid.
NoDeleteWithoutRecord == deleted # {} => record = "good"

\* Every deleted file is the one whose hash is in the record.
DeletesOnlyRecordedContent == \A d \in deleted : d[2] = seen[d[1]]

\* Exit 0 means this run deleted every target, none is present, and the result
\* is saved as completed.
CompletedMeansRunDeletedAll ==
  exitCode = "0" => /\ \A t \in T : file[t] = 0 /\ \E d \in deleted : d[1] = t
                    /\ resultDisk = "completed"

\* Exit 1, or a saved result of failed, means nothing was deleted.
FailedMeansNothingDeleted == (exitCode = "1" \/ resultDisk = "failed") => deleted = {}

\* A rerun reports success only when the first run deleted every target.
RerunZeroMeansAllDeleted == rerunExit = "0" => \A t \in T : \E d \in deleted : d[1] = t

\* A retry that no other process disturbed and that ran to its end completed.
RetryCompletes == (retried /\ pc = "done" /\ outside = 0) => exitCode = "0"
====
