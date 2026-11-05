--------------------------- MODULE AdoptLifecycle ---------------------------
(* runtimes/adopt_lifecycle.py `adopt`: one host switches its live
   workspace-lifecycle install. A run can stop at any step (a kill, or an
   error from git, pip, the lifecycle, Rulesync or CI); the user then runs the
   same command again. Each action is one step of `adopt` or of a function it
   calls. Files are the tracked files of agent-environment that name the
   install: the runtime binding, a rule naming the install (named by
   `git grep`), and a Rulesync export declaration (`reselect_exports`).
   Line numbers are runtimes/adopt_lifecycle.py at agent-environment
   6b9ff054233220e9d3dc9ed126ac42da15767669. *)
EXTENDS Naturals, FiniteSets

CONSTANTS Mutation, MaxFaults

Files == {"runtime", "rule", "decl"}
AllNew == [f \in Files |-> "new"]
AllOld == [f \in Files |-> "old"]
Fixed == Mutation = "fixed"

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


\* live_checkout (L355-365): fetch, then `merge --ff-only` to origin's default branch.
LiveCheckout ==
    /\ Go("start", "install")
    /\ local' = remote
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, outputs, checks, prechecked>>

Same == UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                    committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* install (L144-148): the loop over [old, *sorted(old.parent.glob(version-*))]. After the
\* switch, `old` is the new install and is reused first.
ReuseOld ==
    /\ pc = "install" /\ local["runtime"] = "new"
    /\ pc' = IF Fixed /\ (wt = "open" \/ branch) THEN "resume" ELSE "verify"
    /\ Same

\* The loop reuses an install of this version whose modules match.
ReuseInstall ==
    /\ pc = "install" /\ local["runtime"] = "old" /\ ready
    /\ pc' = "precheck"
    /\ Same

\* The loop (L146) calls venv_python on a prefix without an interpreter, which
\* raises "has no Python interpreter". Sorting by digest can put it before the
\* good install, so this can happen even when `ready`.
HitHalfDir ==
    /\ pc = "install" /\ local["runtime"] = "old" /\ halfDir /\ ~Fixed
    /\ FailSelf("install")

\* No match (L149-164): build a wheel and `python -m venv` a new version-<digest> prefix.
\* Wheel builds are not byte-reproducible, so each build gets a new prefix.
BuildStart ==
    /\ pc = "install" /\ local["runtime"] = "old" /\ ~ready /\ (~halfDir \/ Fixed)
    /\ pc' = "venv"
    /\ Same

VenvDone == Go("venv", "pip") /\ Same

\* pip install --no-index of the kept wheel (L165), then module_mismatches is empty (L168).
PipDone ==
    /\ Go("pip", "precheck")
    /\ ready' = TRUE
    /\ UNCHANGED <<faults, selfFail, halfDir, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* adopt (L374-377): rulesync_states before the switch; every configuration checks true.
Precheck ==
    /\ Go("precheck", "begin")
    /\ prechecked' = TRUE
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks>>

\* integrate (L269): `lifecycle begin` only when the worktree path does not exist.
Begin ==
    /\ pc = "begin" /\ wt = "none"
    /\ pc' = "subject"
    /\ wt' = "open" /\ branch' = TRUE /\ wtFiles' = AllOld
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, staged, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

BeginExisting == pc = "begin" /\ wt = "open" /\ pc' = "subject" /\ Same

\* A retired worktree path no longer exists, so begin would reuse the task name.
BeginRetired == pc = "begin" /\ wt = "retired" /\ FailSelf("switch")

\* integrate (L274): `edit` runs only when HEAD's subject is not the switch subject.
Subject == pc = "subject" /\ pc' = (IF committed THEN "finish" ELSE "repin") /\ Same

\* repin (L176-189): replace the old prefix in the runtime binding and rehash its pins.
\* `git add` always names host.runtime (L284).
Repin ==
    /\ Go("repin", "grep")
    /\ wtFiles' = [wtFiles EXCEPT !["runtime"] = "new"]
    /\ staged' = {"runtime"}
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* edit (L231-234): `git grep -l -F old` lists only files that still name the old prefix,
\* then each is rewritten.
Grep ==
    /\ Go("grep", "reselect")
    /\ wtFiles' = [wtFiles EXCEPT !["rule"] = "new"]
    /\ staged' = staged \cup (IF wtFiles["rule"] = "old" THEN {"rule"} ELSE {})
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* reselect_exports (L217): a declaration whose selected export already has the new
\* name is skipped (`target.name == current.name`) and is not returned.
Reselect ==
    /\ Go("reselect", "add")
    /\ wtFiles' = [wtFiles EXCEPT !["decl"] = "new"]
    /\ staged' = staged \cup (IF wtFiles["decl"] = "old" THEN {"decl"} ELSE {})
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, index, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* integrate (L284): git add -- host.runtime *files *declarations. The fixed variant
\* stages every tracked file that differs from HEAD.
Add ==
    /\ Go("add", "commit")
    /\ index' = index \cup (IF Fixed THEN {f \in Files : wtFiles[f] = "new"} ELSE staged)
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, committed,
                   commitFiles, remote, local, outputs, checks, prechecked>>

\* integrate (L286): git commit.
Commit ==
    /\ Go("commit", "finish")
    /\ committed' = TRUE /\ commitFiles' = index /\ index' = {}
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged,
                   remote, local, outputs, checks, prechecked>>

Dirty == {f \in Files : wtFiles[f] = "new"} \ commitFiles

\* lifecycle finish (L294) with the empty plan `{}` refuses tracked changes the plan
\* does not cover, on every rerun.
FinishRefuses == pc = "finish" /\ Dirty # {} /\ FailSelf("switch")

\* lifecycle finish --wait-checks: the prepared checks pass and the switch
\* commit is integrated into origin's default branch. An earlier failure
\* withdraws the prepared integration and is a Fault at "finish".
Integrate ==
    /\ pc = "finish" /\ Dirty = {}
    /\ pc' = "await"
    /\ remote' = [f \in Files |-> IF f \in commitFiles THEN "new" ELSE remote[f]]
    /\ checks' = "pending"
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, local, outputs, prechecked>>

\* _await_integration_checks on the integrated commit, inside finish (L294).
ChecksPass ==
    /\ Go("await", "retire")
    /\ checks' = "pass"
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, prechecked>>

\* The checks fail: finish returns early, and integrate raises "integrated
\* without successful checks" (L297). The integration stays in the default branch.
ChecksFail ==
    /\ pc = "await" /\ faults < MaxFaults
    /\ checks' = "fail"
    /\ IF Mutation = "ignore-checks"
         THEN pc' = "retire" /\ faults' = faults
         ELSE pc' = "idle" /\ faults' = faults + 1
    /\ UNCHANGED <<selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, prechecked>>

\* The fixed variant reruns when a rerun's checks already failed: it refuses again.
ChecksStillFail ==
    /\ pc = "await" /\ checks = "fail" /\ Fixed
    /\ pc' = "idle"
    /\ Same

\* finish retires and reclaims the task worktree (--users-released).
Retire ==
    /\ Go("retire", "ff")
    /\ wt' = "retired"
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* finish catches a retire error and returns `retirement.pending`; adopt only
\* reports it (L299-302). The fixed variant raises instead.
RetirePending ==
    /\ pc = "retire" /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ pc' = IF Fixed THEN "idle" ELSE "ff"
    /\ UNCHANGED <<selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* integrate (L303-304): fetch and `merge --ff-only` the live checkout.
FastForward ==
    /\ Go("ff", "branch")
    /\ local' = remote
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, outputs, checks, prechecked>>

\* integrate (L305-308): `git branch -d` and `push --delete` of the task branch.
DeleteBranch ==
    /\ Go("branch", "verify")
    /\ branch' = FALSE
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, wtFiles, staged, index,
                   committed, commitFiles, remote, local, outputs, checks, prechecked>>

\* Fixed variant only: a rerun that finds the switch live but its task still
\* open resumes finish, awaiting the integrated commit's checks again.
Resume ==
    /\ pc = "resume"
    /\ pc' = CASE checks = "pass" -> IF wt = "open" THEN "retire" ELSE "branch"
               [] OTHER -> "await"
    /\ Same

\* adopt (L379-380): raise when the runtime binding still selects the previous install.
Verify ==
    /\ pc = "verify"
    /\ IF local["runtime"] = "new" THEN pc' = "apply" /\ Same ELSE FailSelf("switch")

\* apply (L315-328): for each configuration, skip when `check` is true, else apply twice;
\* then every configuration checks true. Rulesync's own transaction is in
\* verify-rulesync-transaction; here one apply makes the outputs match.
Apply ==
    /\ Go("apply", "launch")
    /\ outputs' = IF Mutation = "apply-trusts-precheck" /\ prechecked THEN outputs
                  ELSE local["runtime"]
    /\ UNCHANGED <<faults, selfFail, halfDir, ready, wt, branch, wtFiles, staged, index,
                   committed, commitFiles, remote, local, checks, prechecked>>

\* launch (L331-352): agent-runtime --explain resolves the new install, then "adopted" (L383).
Launch == Go("launch", "adopted") /\ Same

Done == pc = "adopted" /\ pc' = pc /\ Same

Next ==
    \/ Fault \/ Rerun \/ LiveCheckout
    \/ ReuseOld \/ ReuseInstall \/ HitHalfDir \/ BuildStart \/ VenvDone \/ PipDone
    \/ Precheck \/ Begin \/ BeginExisting \/ BeginRetired \/ Subject
    \/ Repin \/ Grep \/ Reselect \/ Add \/ Commit
    \/ FinishRefuses \/ Integrate \/ ChecksPass \/ ChecksFail \/ ChecksStillFail
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
