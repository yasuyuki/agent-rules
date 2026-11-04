---- MODULE GuardedDelete ----
\* One run of agent-environment retention/guarded_delete.py over two targets,
\* the process being killed or raising at any step, another writer in the root,
\* and a later run with the same arguments. Each action is one step of the code.
EXTENDS Naturals, FiniteSets

CONSTANTS Mutation, Windows, MaxOutside, MaxFaults

T == {1, 2}
N == 2
Running == {"inspect", "writeRecord", "verify", "check", "unlink", "finalRead"}

VARIABLES pc, i, file, nextVer, seen, record, deleted, removed, err, interrupted,
          status, code, exitCode, resultDisk, faults, outside, rerunExit

vars == <<pc, i, file, nextVer, seen, record, deleted, removed, err, interrupted,
          status, code, exitCode, resultDisk, faults, outside, rerunExit>>

\* file[t] is the identity of what is at target t, 0 when absent.
\* deleted holds <<t, identity>> for each file this run unlinked.
TypeOK ==
  /\ pc \in Running \cup {"conclude", "saveResult", "done", "killed"}
  /\ i \in 1..N
  /\ file \in [T -> 0..nextVer] /\ seen \in [T -> 0..nextVer]
  /\ record \in {"none", "bad", "good"}
  /\ deleted \subseteq (T \X (1..nextVer)) /\ removed \in 0..N
  /\ err \in BOOLEAN /\ interrupted \in BOOLEAN
  /\ status \in {"none", "completed", "partial", "failed"}
  /\ code \in {"none", "0", "1", "3"}
  /\ exitCode \in {"none", "0", "1", "3", "raised"}
  /\ resultDisk \in {"none", "completed", "partial", "failed"}
  /\ rerunExit \in {"none", "0", "2"}

Init ==
  /\ pc = "inspect" /\ i = 1
  /\ file = [t \in T |-> t] /\ nextVer = N + 1 /\ seen = [t \in T |-> 0]
  /\ record = "none" /\ deleted = {} /\ removed = 0
  /\ err = FALSE /\ interrupted = FALSE
  /\ status = "none" /\ code = "none" /\ exitCode = "none" /\ resultDisk = "none"
  /\ faults = 0 /\ outside = 0 /\ rerunExit = "none"

Fail == err' = TRUE /\ pc' = "conclude"

Next1(after) == IF i < N THEN i' = i + 1 /\ pc' = pc ELSE i' = 1 /\ pc' = after

\* preserve_and_delete: inspect then describe each target; a missing target raises.
Inspect ==
  /\ pc = "inspect"
  /\ IF file[i] = 0
       THEN Fail /\ UNCHANGED <<i, seen>>
       ELSE seen' = [seen EXCEPT ![i] = file[i]] /\ Next1("writeRecord") /\ UNCHANGED err
  /\ UNCHANGED <<file, nextVer, record, deleted, removed, interrupted, status, code,
                 exitCode, resultDisk, faults, outside, rerunExit>>

\* write_new, read_back and validate_record of the record.
WriteRecord ==
  /\ pc = "writeRecord"
  /\ record' = "good" /\ pc' = "verify"
  /\ UNCHANGED <<i, file, nextVer, seen, deleted, removed, err, interrupted, status, code,
                 exitCode, resultDisk, faults, outside, rerunExit>>

\* write_new published a record that read_back finds different.
RecordReadsBackWrong ==
  /\ pc = "writeRecord" /\ faults < MaxFaults
  /\ record' = "bad" /\ faults' = faults + 1
  /\ IF Mutation = "skip-readback" THEN pc' = "verify" /\ UNCHANGED err ELSE Fail
  /\ UNCHANGED <<i, file, nextVer, seen, deleted, removed, interrupted, status, code,
                 exitCode, resultDisk, outside, rerunExit>>

\* The loop after the record: inspect again, compare identity, hash again.
Verify ==
  /\ pc = "verify"
  /\ IF file[i] # seen[i] THEN Fail /\ UNCHANGED i ELSE Next1("check") /\ UNCHANGED err
  /\ UNCHANGED <<file, nextVer, seen, record, deleted, removed, interrupted, status, code,
                 exitCode, resultDisk, faults, outside, rerunExit>>

\* Deletion loop: inspect and compare identity with the first inspection.
Check ==
  /\ pc = "check"
  /\ IF file[i] # seen[i] THEN Fail ELSE pc' = "unlink" /\ UNCHANGED err
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, interrupted, status, code,
                 exitCode, resultDisk, faults, outside, rerunExit>>

\* remove(): os.unlink(path) outside Windows; on Windows a handle opened by path,
\* whose identity is compared with the first inspection before it is deleted.
Unlink ==
  /\ pc = "unlink"
  /\ IF file[i] = 0
          \/ (Windows /\ Mutation # "no-handle-check" /\ file[i] # seen[i])
       THEN Fail /\ UNCHANGED <<i, file, deleted, removed>>
       ELSE /\ deleted' = deleted \cup {<<i, file[i]>>}
            /\ file' = [file EXCEPT ![i] = 0]
            /\ removed' = removed + 1
            /\ IF i < N THEN i' = i + 1 /\ pc' = "check" ELSE i' = 1 /\ pc' = "finalRead"
            /\ UNCHANGED err
  /\ UNCHANGED <<nextVer, seen, record, interrupted, status, code, exitCode, resultDisk,
                 faults, outside, rerunExit>>

\* The final read_back of the record succeeds; its failure is a Fault.
FinalRead ==
  /\ pc = "finalRead" /\ pc' = "conclude"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, err, interrupted, status,
                 code, exitCode, resultDisk, faults, outside, rerunExit>>

\* Any call in preserve_and_delete raises: an OSError, a Stop, or an interruption
\* that run() catches as BaseException.
Fault ==
  /\ pc \in Running /\ faults < MaxFaults
  /\ faults' = faults + 1
  /\ \E stop \in BOOLEAN : interrupted' = stop
  /\ Fail
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, status, code, exitCode,
                 resultDisk, outside, rerunExit>>

\* conclude(): only targets in a validated record count; the filesystem decides.
Recorded == record = "good"
Gone == {t \in T : Recorded /\ file[t] = 0}
Conclude ==
  /\ pc = "conclude"
  /\ LET checked == Recorded /\ Mutation # "trust-own-count"
         bad == err \/ (checked /\ Cardinality(Gone) # removed) \/ (checked /\ Gone # T) \/ ~Recorded
     IN IF bad
          THEN IF Gone # {} THEN status' = "partial" /\ code' = "3"
                            ELSE status' = "failed" /\ code' = "1"
          ELSE status' = "completed" /\ code' = "0"
  /\ pc' = "saveResult"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, err, interrupted, exitCode,
                 resultDisk, faults, outside, rerunExit>>

\* save_result(): write_new and read_back of FILE.result.json, then the exit code;
\* an interruption is raised again after the result is saved.
Exit(c) == exitCode' = IF interrupted THEN "raised" ELSE c
SaveResult ==
  /\ pc = "saveResult"
  /\ resultDisk' = status /\ Exit(code) /\ pc' = "done"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, err, interrupted, status,
                 code, faults, outside, rerunExit>>

SaveResultFails ==
  /\ pc = "saveResult" /\ faults < MaxFaults
  /\ faults' = faults + 1
  /\ Exit(IF status = "completed" THEN "3" ELSE code) /\ pc' = "done"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, err, interrupted, status,
                 code, resultDisk, outside, rerunExit>>

\* The process is killed; nothing after this runs.
Kill ==
  /\ pc \notin {"done", "killed"}
  /\ pc' = "killed"
  /\ UNCHANGED <<i, file, nextVer, seen, record, deleted, removed, err, interrupted, status,
                 code, exitCode, resultDisk, faults, outside, rerunExit>>

\* Another process writes a new file at a target, or deletes one, while the run
\* works or after it was killed.
OutsideWrite ==
  /\ outside < MaxOutside /\ pc \notin {"saveResult", "done"}
  /\ \E t \in T :
       \/ file' = [file EXCEPT ![t] = nextVer] /\ nextVer' = nextVer + 1
       \/ file[t] # 0 /\ file' = [file EXCEPT ![t] = 0] /\ UNCHANGED nextVer
  /\ outside' = outside + 1
  /\ UNCHANGED <<pc, i, seen, record, deleted, removed, err, interrupted, status, code,
                 exitCode, resultDisk, faults, rerunExit>>

\* already_completed(): the same arguments again once a record exists.
Rerun ==
  /\ pc \in {"done", "killed"} /\ record # "none" /\ rerunExit = "none"
  /\ rerunExit' =
       IF record = "good" /\ \A t \in T : file[t] = 0
          /\ (resultDisk = "completed" \/ Mutation = "rerun-without-result")
       THEN "0" ELSE "2"
  /\ UNCHANGED <<pc, i, file, nextVer, seen, record, deleted, removed, err, interrupted,
                 status, code, exitCode, resultDisk, faults, outside>>

Finished == pc \in {"done", "killed"} /\ UNCHANGED vars

Next == Inspect \/ WriteRecord \/ RecordReadsBackWrong \/ Verify \/ Check \/ Unlink
        \/ FinalRead \/ Fault \/ Conclude \/ SaveResult \/ SaveResultFails \/ Kill
        \/ OutsideWrite \/ Rerun \/ Finished

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

\* Exit 1 means nothing was deleted.
FailedMeansNothingDeleted == exitCode = "1" => deleted = {}

\* A rerun reports success only when the first run deleted every target.
RerunZeroMeansAllDeleted == rerunExit = "0" => \A t \in T : \E d \in deleted : d[1] = t
====
