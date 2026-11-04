---- MODULE RulesyncTransaction ----
\* One `apply` of bin/rulesync_backend.py over two outputs: "rule" is a file
\* at the output root such as AGENTS.md, and "skill" is SKILL.md inside a skill
\* directory that apply may have to create. Each action is one filesystem call.
EXTENDS Naturals, FiniteSets

CONSTANTS Mutation, MaxCrashes, MaxFaults, MaxUserEdits

Files == {"rule", "skill"}
Vals == {"absent", "old", "new", "user"}
Recorded == {"absent", "old", "new"}
Mutations == {"none", "skip-unowned-check", "recover-skip-conflict",
              "no-journal", "no-temp-cleanup"}

VARIABLES
    disk,      \* content of each output path; "user" is anything the adapter did not write
    dExists,   \* the skill directory exists
    tmpD,      \* .SKILL.md.rulesync-tmp-* files inside the skill directory
    mf,        \* .rulesync-ownership.json: recorded content of each owned path
    want,      \* generated output of this configuration
    jr,        \* .rulesync-transaction.json
    plan,      \* the in-memory backups and plan of the running _apply_reconcile
    pc,
    todo,
    crashes, faults, edits,
    lost,      \* the adapter replaced or deleted content it did not write
    stuck,     \* apply refused although nobody but the adapter touched the output
    userEver,
    touched,   \* paths the user changed since the last transaction began
    snap       \* output before and after the last transaction

vars == <<disk, dExists, tmpD, mf, want, jr, plan, pc, todo, crashes, faults,
          edits, lost, stuck, userEver, touched, snap>>

Absent == [f \in Files |-> "absent"]
NoJournal == [on |-> FALSE, files |-> {}, before |-> Absent, after |-> Absent,
              mfTouched |-> FALSE, mfBefore |-> Absent, mfAfter |-> Absent,
              mkD |-> FALSE]

Snapshot(pre, preMf, preD, post, postMf, postD) ==
    [pre |-> pre, preMf |-> preMf, preD |-> preD,
     post |-> post, postMf |-> postMf, postD |-> postD]

SetDisk(f, v) ==
    /\ disk' = [disk EXCEPT ![f] = v]
    /\ lost' = (lost \/ (disk[f] = "user" /\ v # "user"))

Refuse ==
    /\ pc' = "idle"
    /\ stuck' = (stuck \/ ~userEver)

Init ==
    /\ want \in [Files -> {"absent", "new"}]
    /\ mf \in [Files -> {"absent", "old"}]
    /\ disk \in {d \in [Files -> Vals] :
                   \A f \in Files : IF mf[f] = "old" THEN d[f] = "old"
                                    ELSE d[f] \in {"absent", "user"}}
    /\ dExists = (disk["skill"] # "absent")
    /\ tmpD = 0
    /\ jr = NoJournal
    /\ plan = NoJournal
    /\ pc = "idle"
    /\ todo = {}
    /\ crashes = 0 /\ faults = 0 /\ edits = 0
    /\ lost = FALSE /\ stuck = FALSE
    /\ userEver = (\E f \in Files : disk[f] = "user")
    /\ touched = {}
    /\ snap = Snapshot(disk, mf, dExists, disk, mf, dExists)

\* apply(): take _output_lock, then _recover only when a journal exists.
StartApply ==
    /\ pc = "idle"
    /\ pc' = IF jr.on THEN "recover" ELSE "validate"
    /\ UNCHANGED <<disk, dExists, tmpD, mf, want, jr, plan, todo, crashes, faults,
                   edits, lost, stuck, userEver, touched, snap>>

\* _recover: every journaled path must still hold its before or after bytes.
\* Then it deletes the .<name>.rulesync-tmp-* files beside the journaled paths.
RecoverCheck ==
    /\ pc = "recover"
    /\ IF /\ Mutation # "recover-skip-conflict"
          /\ \/ \E f \in jr.files : disk[f] \notin {jr.before[f], jr.after[f]}
             \/ jr.mfTouched /\ mf \notin {jr.mfBefore, jr.mfAfter}
       THEN Refuse /\ UNCHANGED <<todo, tmpD>>
       ELSE /\ pc' = "rrestore"
            /\ todo' = jr.files \cup (IF jr.mfTouched THEN {"M"} ELSE {})
            /\ tmpD' = IF Mutation = "no-temp-cleanup" THEN tmpD ELSE 0
            /\ UNCHANGED stuck
    /\ UNCHANGED <<disk, dExists, mf, want, jr, plan, crashes, faults,
                   edits, lost, userEver, touched, snap>>

\* _restore: unlink, skip, or _write_atomic each backup. "M" is the manifest.
RestoreStep(J, here, replacing, next) ==
    /\ pc = here
    /\ IF todo = {}
       THEN pc' = next /\ UNCHANGED <<disk, lost, tmpD, mf, todo>>
       ELSE \E x \in todo :
              CASE x = "M" ->
                     /\ mf' = J.mfBefore /\ todo' = todo \ {x}
                     /\ UNCHANGED <<disk, lost, tmpD, pc>>
                [] J.before[x] = disk[x] ->
                     /\ todo' = todo \ {x}
                     /\ UNCHANGED <<disk, lost, tmpD, mf, pc>>
                [] J.before[x] = "absent" ->
                     /\ SetDisk(x, "absent") /\ todo' = todo \ {x}
                     /\ UNCHANGED <<tmpD, mf, pc>>
                [] x = "skill" ->
                     /\ tmpD' = tmpD + 1 /\ pc' = replacing
                     /\ UNCHANGED <<disk, lost, mf, todo>>
                [] OTHER ->
                     /\ SetDisk(x, J.before[x]) /\ todo' = todo \ {x}
                     /\ UNCHANGED <<tmpD, mf, pc>>
    /\ UNCHANGED <<dExists, want, jr, plan, crashes, faults, edits, stuck,
                   userEver, touched, snap>>

\* The os.replace half of _write_atomic inside the skill directory.
ReplaceStep(here, back, value) ==
    /\ pc = here
    /\ SetDisk("skill", value)
    /\ tmpD' = tmpD - 1
    /\ todo' = todo \ {"skill"}
    /\ pc' = back
    /\ UNCHANGED <<dExists, mf, want, jr, plan, crashes, faults, edits, stuck,
                   userEver, touched, snap>>

RecoverRestore == RestoreStep(jr, "rrestore", "rreplace", "rrmdir")
RecoverReplace == ReplaceStep("rreplace", "rrestore", jr.before["skill"])

\* _recover: rmdir each directory the transaction created; OSError if not empty.
RecoverRmdir ==
    /\ pc = "rrmdir"
    /\ IF jr.mkD /\ dExists
       THEN IF tmpD > 0 \/ disk["skill"] # "absent"
            THEN Refuse /\ UNCHANGED dExists
            ELSE dExists' = FALSE /\ pc' = "runjournal" /\ UNCHANGED stuck
       ELSE pc' = "runjournal" /\ UNCHANGED <<dExists, stuck>>
    /\ UNCHANGED <<disk, tmpD, mf, want, jr, plan, todo, crashes, faults, edits,
                   lost, userEver, touched, snap>>

RecoverDone ==
    /\ pc = "runjournal"
    /\ jr' = NoJournal
    /\ pc' = "validate"
    /\ UNCHANGED <<disk, dExists, tmpD, mf, want, plan, todo, crashes, faults,
                   edits, lost, stuck, userEver, touched, snap>>

Stale == {f \in Files : mf[f] # "absent" /\ want[f] = "absent"}
Writes == {f \in Files : want[f] = "new" /\ disk[f] # "new"}
MfAfter == [f \in Files |-> IF want[f] = "new" THEN "new" ELSE "absent"]

\* _validate_reconcile: externally modified owned file, unowned file would be
\* replaced, and unowned same-name skill (any file in the skill directory
\* that the manifest does not own, or a directory the manifest never owned).
Blocked ==
    \/ \E f \in Files : mf[f] # "absent" /\ disk[f] # mf[f]
    \/ /\ Mutation # "skip-unowned-check"
       /\ \E f \in Files : want[f] = "new" /\ disk[f] # "absent" /\ mf[f] = "absent"
    \/ /\ dExists
       /\ want["skill"] = "new" \/ mf["skill"] # "absent"
       /\ tmpD > 0 \/ mf["skill"] = "absent"

\* _plan, then _write_atomic of the journal before any output changes.
Validate ==
    /\ pc = "validate"
    /\ IF Blocked
       THEN Refuse /\ UNCHANGED <<jr, plan, todo, touched, snap>>
       ELSE IF Stale = {} /\ Writes = {} /\ mf = MfAfter
       THEN pc' = "idle" /\ UNCHANGED <<jr, plan, todo, stuck, touched, snap>>
       ELSE LET J == [on |-> TRUE, files |-> Stale \cup Writes, before |-> disk,
                      after |-> [f \in Files |-> IF f \in Writes THEN "new"
                                                 ELSE IF f \in Stale THEN "absent"
                                                 ELSE disk[f]],
                      mfTouched |-> mf # MfAfter, mfBefore |-> mf,
                      mfAfter |-> MfAfter,
                      mkD |-> "skill" \in Writes /\ ~dExists]
            IN /\ plan' = J
               /\ jr' = IF Mutation = "no-journal" THEN NoJournal ELSE J
               /\ pc' = "mkdir"
               /\ todo' = {}
               /\ touched' = {}
               /\ snap' = Snapshot(disk, mf, dExists, J.after, MfAfter,
                                   dExists \/ want["skill"] = "new")
               /\ UNCHANGED stuck
    /\ UNCHANGED <<disk, dExists, tmpD, mf, want, crashes, faults, edits, lost,
                   userEver>>

Mkdir ==
    /\ pc = "mkdir"
    /\ dExists' = (dExists \/ plan.mkD)
    /\ pc' = "stale"
    /\ todo' = {f \in plan.files : plan.after[f] = "absent"}
    /\ UNCHANGED <<disk, tmpD, mf, want, jr, plan, crashes, faults, edits, lost,
                   stuck, userEver, touched, snap>>

UnlinkStale ==
    /\ pc = "stale"
    /\ IF todo = {}
       THEN /\ pc' = "write"
            /\ todo' = {f \in plan.files : plan.after[f] = "new"}
            /\ UNCHANGED <<disk, lost>>
       ELSE \E f \in todo :
              /\ SetDisk(f, "absent") /\ todo' = todo \ {f}
              /\ UNCHANGED pc
    /\ UNCHANGED <<dExists, tmpD, mf, want, jr, plan, crashes, faults, edits,
                   stuck, userEver, touched, snap>>

\* The mkstemp half of _write_atomic; "rule" is written in one step.
WriteFile ==
    /\ pc = "write"
    /\ IF todo = {}
       THEN pc' = "manifest" /\ UNCHANGED <<disk, lost, tmpD, todo>>
       ELSE \E f \in todo :
              IF f = "skill"
              THEN tmpD' = tmpD + 1 /\ pc' = "replace" /\ UNCHANGED <<disk, lost, todo>>
              ELSE SetDisk(f, "new") /\ todo' = todo \ {f} /\ UNCHANGED <<pc, tmpD>>
    /\ UNCHANGED <<dExists, mf, want, jr, plan, crashes, faults, edits, stuck,
                   userEver, touched, snap>>

ApplyReplace == ReplaceStep("replace", "write", "new")

WriteManifest ==
    /\ pc = "manifest"
    /\ mf' = IF plan.mfTouched THEN plan.mfAfter ELSE mf
    /\ pc' = "unjournal"
    /\ UNCHANGED <<disk, dExists, tmpD, want, jr, plan, todo, crashes, faults,
                   edits, lost, stuck, userEver, touched, snap>>

Commit ==
    /\ pc = "unjournal"
    /\ jr' = NoJournal
    /\ pc' = "idle"
    /\ UNCHANGED <<disk, dExists, tmpD, mf, want, plan, todo, crashes, faults,
                   edits, lost, stuck, userEver, touched, snap>>

\* An exception inside the try block; _write_atomic's finally removes its own
\* temporary file, then _apply_reconcile restores the backups.
Fault ==
    /\ pc \in {"mkdir", "stale", "write", "replace", "manifest", "unjournal"}
    /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ tmpD' = IF pc = "replace" THEN tmpD - 1 ELSE tmpD
    /\ pc' = "brestore"
    /\ todo' = plan.files \cup (IF plan.mfTouched THEN {"M"} ELSE {})
    /\ UNCHANGED <<disk, dExists, mf, want, jr, plan, crashes, edits, lost,
                   stuck, userEver, touched, snap>>

RollbackRestore == RestoreStep(plan, "brestore", "breplace", "brmdir")
RollbackReplace == ReplaceStep("breplace", "brestore", plan.before["skill"])

\* A failing rmdir raises "rollback failed" and leaves the journal for _recover.
RollbackRmdir ==
    /\ pc = "brmdir"
    /\ IF plan.mkD /\ dExists
       THEN IF tmpD > 0 \/ disk["skill"] # "absent"
            THEN pc' = "idle" /\ UNCHANGED dExists
            ELSE dExists' = FALSE /\ pc' = "bunjournal"
       ELSE pc' = "bunjournal" /\ UNCHANGED dExists
    /\ UNCHANGED <<disk, tmpD, mf, want, jr, plan, todo, crashes, faults, edits,
                   lost, stuck, userEver, touched, snap>>

RollbackDone ==
    /\ pc = "bunjournal"
    /\ jr' = NoJournal
    /\ pc' = "idle"
    /\ UNCHANGED <<disk, dExists, tmpD, mf, want, plan, todo, crashes, faults,
                   edits, lost, stuck, userEver, touched, snap>>

\* The process is killed: no finally block runs, temporary files stay.
Crash ==
    /\ pc # "idle"
    /\ crashes < MaxCrashes
    /\ crashes' = crashes + 1
    /\ pc' = "idle"
    /\ todo' = {}
    /\ UNCHANGED <<disk, dExists, tmpD, mf, want, jr, plan, faults, edits, lost,
                   stuck, userEver, touched, snap>>

\* The user edits or deletes an output while no apply runs.
UserEdit ==
    /\ pc = "idle"
    /\ edits < MaxUserEdits
    /\ \E f \in Files, v \in {"user", "absent"} :
         /\ disk[f] # v
         /\ disk' = [disk EXCEPT ![f] = v]
         /\ dExists' = IF f = "skill" /\ v = "user" THEN TRUE ELSE dExists
         /\ touched' = touched \cup {f}
    /\ edits' = edits + 1
    /\ userEver' = TRUE
    /\ UNCHANGED <<tmpD, mf, want, jr, plan, pc, todo, crashes, faults, lost,
                   stuck, snap>>

Next ==
    \/ StartApply \/ RecoverCheck \/ RecoverRestore \/ RecoverReplace
    \/ RecoverRmdir \/ RecoverDone \/ Validate \/ Mkdir \/ UnlinkStale
    \/ WriteFile \/ ApplyReplace \/ WriteManifest \/ Commit \/ Fault
    \/ RollbackRestore \/ RollbackReplace \/ RollbackRmdir \/ RollbackDone
    \/ Crash \/ UserEdit

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ Mutation \in Mutations
    /\ disk \in [Files -> Vals]
    /\ mf \in [Files -> Recorded]
    /\ tmpD \in 0..(MaxCrashes + 1)
    /\ pc \in {"idle", "recover", "rrestore", "rreplace", "rrmdir", "runjournal",
               "validate", "mkdir", "stale", "write", "replace", "manifest",
               "unjournal", "brestore", "breplace", "brmdir", "bunjournal"}
    /\ todo \subseteq Files \cup {"M"}
    /\ disk["skill"] # "absent" => dExists

\* The adapter never replaces or deletes a file it did not write.
NoClobber == ~lost

Untouched == Files \ touched
AtPre ==
    /\ mf = snap.preMf
    /\ \A f \in Untouched : disk[f] = snap.pre[f]
    /\ "skill" \in touched \/ dExists = snap.preD
AtPost ==
    /\ mf = snap.postMf
    /\ \A f \in Untouched : disk[f] = snap.post[f]
    /\ "skill" \in touched \/ dExists = snap.postD

\* With no apply running and no journal pending, outputs and the manifest are
\* entirely before or entirely after the last transaction.
AllOrNothing == (pc = "idle" /\ ~jr.on) => (AtPre \/ AtPost)

\* A crash alone never leaves apply refusing until someone repairs the output.
NoStuck == ~stuck
====
