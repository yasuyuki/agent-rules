--------------------------- MODULE AdoptLifecycle ---------------------------
(* runtimes/adopt_lifecycle.py `adopt`: one host switches its live
   workspace-lifecycle install. A run can stop at any step (a kill, or an
   error from git, pip, the lifecycle, Rulesync or CI); the user then runs the
   same command again. Each action is one step of `adopt` or of a function it
   calls. Files are the tracked files of agent-environment that name the
   install: the runtime binding, a rule naming the install (named by
   `git grep`), and a Rulesync export declaration (`reselect_exports`).
   Line numbers are runtimes/adopt_lifecycle.py at agent-environment
   0ecadc47f39b4964c77b0e0d096384f9c6653ccf. Each mutation other than "none"
   removes one guard of that code. *)
EXTENDS Naturals, FiniteSets

CONSTANTS Mutation, MaxFaults

Files == {"runtime", "rule", "decl"}
AllNew == [f \in Files |-> "new"]
AllOld == [f \in Files |-> "old"]
Mut(name) == Mutation = name

VARIABLES
    pc,          \* step of the current run; "idle" between runs
    faults,      \* runs stopped by a kill or an outside error so far
    selfFail,    \* where a run failed with no outside cause: "none", "install", "switch"
    halfDir,     \* a version-<digest> directory exists without a Python interpreter
    ready,       \* an install whose modules equal the revision exists
    wt,          \* the task worktree: "none", "open", "retired"
    branch,      \* the task branch exists
    wtFiles,     \* file contents in the task worktree
    staged,      \* paths this run's `edit` returned for `git add`
    index,       \* the worktree's Git index
    committed,   \* the task HEAD subject is "Switch the <host> lifecycle to <version>"
    commitFiles, \* files the switch commit changed
    remote,      \* file contents on origin's default branch
    local,       \* file contents in the live checkout (ROOT)
    outputs,     \* what the host's Rulesync outputs were generated from
    checks,      \* required checks on the integrated switch commit, as adopt saw them
    prechecked   \* this run checked the Rulesync configurations before the switch

vars == <<pc, faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
          committed, commitFiles, remote, local, outputs, checks, prechecked>>

TypeOK ==
    /\ faults \in 0..MaxFaults
    /\ selfFail \in {"none", "install", "switch"}
    /\ halfDir \in BOOLEAN /\ ready \in BOOLEAN /\ branch \in BOOLEAN
    /\ committed \in BOOLEAN /\ prechecked \in BOOLEAN
    /\ wt \in {"none", "open", "retired"}
    /\ wtFiles \in [Files -> {"old", "new"}]
    /\ remote \in [Files -> {"old", "new"}] /\ local \in [Files -> {"old", "new"}]
    /\ staged \subseteq Files /\ index \subseteq Files /\ commitFiles \subseteq Files
    /\ outputs \in {"old", "new"}
    /\ checks \in {"none", "pending", "pass", "fail"}

Init ==
    /\ pc = "start" /\ faults = 0 /\ selfFail = "none"
    /\ halfDir = FALSE /\ ready = FALSE /\ wt = "none" /\ branch = FALSE
    /\ wtFiles = AllOld /\ staged = {} /\ index = {} /\ committed = FALSE
    /\ commitFiles = {} /\ remote = AllOld /\ local = AllOld /\ outputs = "old"
    /\ checks = "none" /\ prechecked = FALSE

Go(from, to) == pc = from /\ pc' = to

Same == UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                    committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* `selfFail` keeps the first such failure, so the state space stays finite.
FailSelf(where) ==
    /\ pc' = "idle"
    /\ selfFail' = IF selfFail = "none" THEN where ELSE selfFail
    /\ UNCHANGED <<faults, halfDir, ready, wt, branch, wtFiles, staged, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* A kill or an outside error ends the run where it is. A kill inside
\* `python -m venv <prefix>` leaves the prefix directory without an interpreter.
Fault ==
    /\ pc \notin {"idle", "adopted"}
    /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ pc' = "idle"
    /\ halfDir' = (halfDir \/ pc = "venv")
    /\ UNCHANGED <<selfFail, ready, wt, branch, wtFiles, staged, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* The user runs the same `adopt` command again.
Rerun ==
    /\ Go("idle", "start")
    /\ staged' = {} /\ prechecked' = FALSE
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, index, committed,
                   commitFiles, remote, local, outputs, checks>>

\* live_checkout (L391-400): fetch, then `merge --ff-only` to origin's default branch.
LiveCheckout ==
    /\ Go("start", "install")
    /\ local' = remote
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, outputs, checks, prechecked>>

\* install (L154-157): the loop over [old, *sorted(old.parent.glob(version-*))].
\* After the switch, `old` is the new install and is reused first, and adopt
\* (L410, L415-416) calls resume instead of integrate.
ReuseOld ==
    /\ pc = "install" /\ local["runtime"] = "new"
    /\ pc' = IF Mut("rerun-skips-task") THEN "verify" ELSE "resume"
    /\ Same

\* The loop reuses an install of this version whose modules match.
ReuseInstall ==
    /\ pc = "install" /\ local["runtime"] = "old" /\ ready
    /\ pc' = "precheck"
    /\ Same

\* reusable (L123-130) answers False for a prefix without an interpreter. The
\* mutation calls venv_python on it, which raises "has no Python interpreter";
\* sorting by digest can put it before the good install.
HitHalfDir ==
    /\ pc = "install" /\ local["runtime"] = "old" /\ halfDir
    /\ Mut("install-reuses-half-prefix")
    /\ FailSelf("install")

\* No match (L158-173): build a wheel and `python -m venv` a new version-<digest>
\* prefix. Wheel builds are not byte-reproducible, so each build gets a new prefix.
BuildStart ==
    /\ pc = "install" /\ local["runtime"] = "old" /\ ~ready
    /\ (~halfDir \/ ~Mut("install-reuses-half-prefix"))
    /\ pc' = "venv"
    /\ Same

VenvDone == Go("venv", "pip") /\ Same

\* pip install --no-index of the kept wheel (L174-175), then module_mismatches
\* is empty (L176-179).
PipDone ==
    /\ Go("pip", "precheck")
    /\ ready' = TRUE
    /\ UNCHANGED <<faults, selfFail, halfDir, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* adopt (L410-413): rulesync_states before the switch; every configuration checks true.
Precheck ==
    /\ Go("precheck", "begin")
    /\ prechecked' = TRUE
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks>>

\* integrate (L282): `lifecycle begin` only when the worktree path does not exist.
Begin ==
    /\ pc = "begin" /\ wt = "none"
    /\ pc' = "subject"
    /\ wt' = "open" /\ branch' = TRUE /\ wtFiles' = AllOld
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, staged, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

BeginExisting == pc = "begin" /\ wt = "open" /\ pc' = "subject" /\ Same

\* A retired worktree path no longer exists, so begin would reuse the task name.
BeginRetired == pc = "begin" /\ wt = "retired" /\ FailSelf("switch")

\* integrate (L287-290): `edit` runs only when HEAD's subject is not the switch
\* subject, after `git restore --source=HEAD --staged --worktree` returns the
\* worktree and index to HEAD, where every file names the old install.
Subject ==
    /\ pc = "subject"
    /\ IF committed
         THEN pc' = "finish" /\ Same
         ELSE /\ pc' = "repin"
              /\ IF Mut("edit-without-restore")
                   THEN UNCHANGED <<wtFiles, index>>
                   ELSE wtFiles' = AllOld /\ index' = {}
              /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, staged, committed,
                             commitFiles, remote, local, outputs, checks, prechecked>>

\* repin (L185-198): replace the old prefix in the runtime binding and rehash its pins.
\* `git add` always names host.runtime (L299).
Repin ==
    /\ Go("repin", "grep")
    /\ wtFiles' = [wtFiles EXCEPT !["runtime"] = "new"]
    /\ staged' = {"runtime"}
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* edit (L240-243): `git grep -l -F old` lists only files that still name the old prefix,
\* then each is rewritten.
Grep ==
    /\ Go("grep", "reselect")
    /\ wtFiles' = [wtFiles EXCEPT !["rule"] = "new"]
    /\ staged' = staged \cup (IF wtFiles["rule"] = "old" THEN {"rule"} ELSE {})
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* reselect_exports (L226): a declaration whose selected export already has the new
\* name is skipped (`target.name == current.name`) and is not returned.
Reselect ==
    /\ Go("reselect", "add")
    /\ wtFiles' = [wtFiles EXCEPT !["decl"] = "new"]
    /\ staged' = staged \cup (IF wtFiles["decl"] = "old" THEN {"decl"} ELSE {})
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* integrate (L299-300): git add -- host.runtime *files *declarations.
Add ==
    /\ Go("add", "commit")
    /\ index' = index \cup staged
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* integrate (L301): git commit.
Commit ==
    /\ Go("commit", "finish")
    /\ committed' = TRUE /\ commitFiles' = index /\ index' = {}
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged,
                   remote, local, outputs, checks, prechecked>>

Dirty == {f \in Files : wtFiles[f] = "new"} \ commitFiles

\* lifecycle finish (L309) with the empty plan `{}` refuses tracked changes the plan
\* does not cover, on every rerun.
FinishRefuses == pc = "finish" /\ Dirty # {} /\ FailSelf("switch")

\* lifecycle finish --wait-checks: the prepared checks pass and the switch
\* commit is integrated into origin's default branch. An earlier failure
\* withdraws the prepared integration and is a Fault at "finish". A finish
\* rerun on an integrated task waits for its checks again.
Integrate ==
    /\ pc = "finish" /\ Dirty = {}
    /\ pc' = "await"
    /\ remote' = [f \in Files |-> IF f \in commitFiles THEN "new" ELSE remote[f]]
    /\ checks' = "pending"
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, local, outputs, prechecked>>

\* _await_integration_checks on the integrated commit, inside finish (L309).
ChecksPass ==
    /\ Go("await", "retire")
    /\ checks' = "pass"
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, prechecked>>

\* The checks fail: finish returns early, and integrate raises "integrated
\* without successful checks" (L312-313). The integration stays in the default branch.
ChecksFail ==
    /\ pc = "await" /\ faults < MaxFaults
    /\ checks' = "fail"
    /\ IF Mutation = "ignore-checks"
         THEN pc' = "retire" /\ faults' = faults
         ELSE pc' = "idle" /\ faults' = faults + 1
    /\ UNCHANGED <<selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, prechecked>>

\* finish retires and reclaims the task worktree (--users-released).
Retire ==
    /\ Go("retire", "ff")
    /\ wt' = "retired"
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* finish catches a retire error and returns `retirement.pending`; integrate
\* raises "is integrated but not retired" (L318-319).
RetirePending ==
    /\ pc = "retire" /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ pc' = IF Mut("pending-retire-adopts") THEN "ff" ELSE "idle"
    /\ UNCHANGED <<selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* integrate (L320-321): fetch and `merge --ff-only` the live checkout.
FastForward ==
    /\ Go("ff", "branch")
    /\ local' = remote
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, outputs, checks, prechecked>>

\* delete_branch (L325-335): `git branch -d` and `push --delete` of the task
\* branch once origin's default branch has it.
DeleteBranch ==
    /\ Go("branch", "verify")
    /\ branch' = FALSE
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* resume (L338-344): integrate when the task worktree still exists, which
\* skips begin and edit and reruns finish; otherwise delete_branch only.
Resume ==
    /\ pc = "resume"
    /\ pc' = IF wt = "open" THEN "begin" ELSE "branch"
    /\ Same

\* adopt (L417-418): raise when the runtime binding still selects the previous install.
Verify ==
    /\ pc = "verify"
    /\ IF local["runtime"] = "new" THEN pc' = "apply" /\ Same ELSE FailSelf("switch")

\* apply (L351-364): for each configuration, skip when `check` is true, else apply twice;
\* then every configuration checks true. Rulesync's own transaction is in
\* verify-rulesync-transaction; here one apply makes the outputs match.
Apply ==
    /\ Go("apply", "launch")
    /\ outputs' = IF Mutation = "apply-trusts-precheck" /\ prechecked THEN outputs
                  ELSE local["runtime"]
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, checks, prechecked>>

\* launch (L367-388): agent-runtime --explain resolves the new install, then "adopted" (L421).
Launch == Go("launch", "adopted") /\ Same

Done == pc = "adopted" /\ pc' = pc /\ Same

Next ==
    \/ Fault \/ Rerun \/ LiveCheckout
    \/ ReuseOld \/ ReuseInstall \/ HitHalfDir \/ BuildStart \/ VenvDone \/ PipDone
    \/ Precheck \/ Begin \/ BeginExisting \/ BeginRetired \/ Subject
    \/ Repin \/ Grep \/ Reselect \/ Add \/ Commit
    \/ FinishRefuses \/ Integrate \/ ChecksPass \/ ChecksFail
    \/ Retire \/ RetirePending \/ FastForward \/ DeleteBranch \/ Resume
    \/ Verify \/ Apply \/ Launch \/ Done

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Promises *)

\* After a run fails, rerunning the install step never fails on what the
\* failed run left behind.
InstallResumes == selfFail # "install"

\* After a run fails, rerunning the switch never fails on what the failed run
\* left behind.
SwitchResumes == selfFail # "switch"

\* adopt reports "adopted" only after it saw the switch commit's required
\* checks succeed.
AdoptedAfterChecks == pc = "adopted" => checks = "pass"

\* adopt reports "adopted" only when the switch task is retired and its branch
\* is gone.
AdoptedLeavesNoTask == pc = "adopted" => wt = "retired" /\ ~branch

\* "adopted" means the default branch, the live checkout and the Rulesync
\* outputs all name the new install, and the install exists.
AdoptedIsLive ==
    pc = "adopted" => remote = AllNew /\ local = AllNew /\ outputs = "new" /\ ready
=============================================================================
