---- MODULE PlacementRouting ----
\* Which environment a change starts in, and whether that session can carry
\* the change into every environment whose placement it must update.
\*
\* Sources (see SKILL.md Coverage for the commits):
\*  - work-records README "開発を行う場所" and
\*    rules/rulesync/windows-controller/rules/workspace.md: the routing rule.
\*  - agent-rules skills/maintain-environment-inventory "Select an environment".
\*  - agent-environment pstack/environments.json: every recorded placement
\*    route. All of them run from windows-controller (empty transport is local,
\*    the others are ssh.exe and wsl.exe). No other environment has a route.
\*  - work-records #258 (2026-11-17): ubuntu-26-development blocks every route
\*    to the Windows host. Source edits and builds happen only there.
\*  - work-records #260 and pstack/sync.py delegate: windows-controller starts
\*    a non-interactive agent on ubuntu-26-development (DELEGATE_ENV).
EXTENDS FiniteSets

CONSTANT Rule
\* "by-target"        the rule after the fix: start where every target is reachable
\* "by-repo-kind"     the rule before the fix: management repo work starts on
\*                    ubuntu-26-development whatever it must update
\* "controller-edits" the controller edits source in its own checkout instead
\*                    of delegating

Ctl == "windows-controller"
Op  == "ubuntu-operator"
Dev == "ubuntu-26-development"
Envs == {Ctl, Op, Dev}

\* pstack/environments.json: routes exist only from windows-controller.
Reach(s) == IF s = Ctl THEN Envs ELSE {s}

\* The environment a session for a change with these targets starts in.
Start(t) ==
    IF Rule = "by-repo-kind" THEN Dev
    ELSE IF t = {Dev} THEN Dev ELSE Ctl

VARIABLES targets, session, editedAt, integrated, applied
vars == <<targets, session, editedAt, integrated, applied>>

TypeOK ==
    /\ targets \in (SUBSET Envs) \ {{}}
    /\ session \in Envs
    /\ editedAt \in Envs \cup {"none"}
    /\ integrated \in BOOLEAN
    /\ applied \subseteq targets

Init ==
    /\ targets \in (SUBSET Envs) \ {{}}
    /\ session = Start(targets)
    /\ editedAt = "none"
    /\ integrated = FALSE
    /\ applied = {}

\* The session itself is on ubuntu-26-development and edits the task checkout.
EditHere ==
    /\ editedAt = "none" /\ session = Dev
    /\ editedAt' = Dev
    /\ UNCHANGED <<targets, session, integrated, applied>>

\* sync.py delegate: the controller hands the source work to ubuntu-26-development.
Delegate ==
    /\ editedAt = "none" /\ session # Dev /\ Dev \in Reach(session)
    /\ Rule # "controller-edits"
    /\ editedAt' = Dev
    /\ UNCHANGED <<targets, session, integrated, applied>>

EditOnController ==
    /\ editedAt = "none" /\ session = Ctl /\ Rule = "controller-edits"
    /\ editedAt' = Ctl
    /\ UNCHANGED <<targets, session, integrated, applied>>

\* lifecycle finish pushes to GitHub, which every environment reaches.
Integrate ==
    /\ editedAt # "none" /\ ~integrated
    /\ integrated' = TRUE
    /\ UNCHANGED <<targets, session, editedAt, applied>>

\* Rulesync apply/check/reapply through the environment's recorded route.
Apply(e) ==
    /\ integrated /\ e \in targets \ applied /\ e \in Reach(session)
    /\ applied' = applied \cup {e}
    /\ UNCHANGED <<targets, session, editedAt, integrated>>

Done == applied = targets

Next ==
    \/ EditHere \/ Delegate \/ EditOnController \/ Integrate
    \/ \E e \in Envs : Apply(e)
    \/ (Done /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

\* Promise: after integration, the session can always place the change in
\* some environment it still has to update. Harm when broken: the session
\* ends with a target unplaced, and the owner must notice and relay it.
PlacementNeverStalls ==
    (integrated /\ ~Done) => \E e \in targets \ applied : e \in Reach(session)

\* Promise: source is edited only on ubuntu-26-development (#258).
\* Harm when broken: management repos are edited and built on the controller.
SourceEditedOnDevelopment == editedAt \in {"none", Dev}
====
