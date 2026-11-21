---- MODULE PlacementRouting ----
\* Which environment a change starts in, and whether that session can carry
\* the change into every environment whose placement it must update.
\*
\* Sources (see SKILL.md Coverage for the commits):
\*  - work-records README "開発を行う場所" and
\*    rules/rulesync/windows-controller/rules/workspace.md: the routing rule.
\*    Since 2026-11-19 every development session starts on windows-controller
\*    and ubuntu-26-development only takes wl validation offload
\*    (workspace-lifecycle-native ADR 0001).
\*  - agent-rules skills/maintain-environment-inventory "Select an environment".
\*  - agent-environment pstack/environments.json: every recorded placement
\*    route. All of them run from windows-controller (empty transport is local,
\*    the others are ssh.exe and wsl.exe). No other environment has a route.
\*  - work-records #258 (2026-11-17): ubuntu-26-development blocks every route
\*    to the Windows host; it reaches itself and GitHub.
EXTENDS FiniteSets

CONSTANT Rule
\* "windows-sessions" the current rule: every session starts on windows-controller
\* "by-repo-kind"     the stale workspace rule before #265: management repo work
\*                    starts on ubuntu-26-development whatever it must update
\* "by-target"        start on ubuntu-26-development when it is the only target,
\*                    as 6c01142 wrote; it starts new sessions there

Ctl == "windows-controller"
Op  == "ubuntu-operator"
Dev == "ubuntu-26-development"
Envs == {Ctl, Op, Dev}

\* pstack/environments.json: routes exist only from windows-controller.
Reach(s) == IF s = Ctl THEN Envs ELSE {s}

\* The environment a session for a change with these targets starts in.
Start(t) ==
    CASE Rule = "windows-sessions" -> Ctl
      [] Rule = "by-repo-kind"     -> Dev
      [] Rule = "by-target"        -> IF t = {Dev} THEN Dev ELSE Ctl

VARIABLES targets, session, edited, integrated, applied
vars == <<targets, session, edited, integrated, applied>>

TypeOK ==
    /\ targets \in (SUBSET Envs) \ {{}}
    /\ session \in Envs
    /\ edited \in BOOLEAN
    /\ integrated \in BOOLEAN
    /\ applied \subseteq targets

Init ==
    /\ targets \in (SUBSET Envs) \ {{}}
    /\ session = Start(targets)
    /\ edited = FALSE
    /\ integrated = FALSE
    /\ applied = {}

\* The session edits its registered task checkout (lifecycle begin).
Edit ==
    /\ ~edited
    /\ edited' = TRUE
    /\ UNCHANGED <<targets, session, integrated, applied>>

\* lifecycle finish pushes to GitHub, which every environment reaches.
Integrate ==
    /\ edited /\ ~integrated
    /\ integrated' = TRUE
    /\ UNCHANGED <<targets, session, edited, applied>>

\* Rulesync apply/check/reapply through the environment's recorded route.
Apply(e) ==
    /\ integrated /\ e \in targets \ applied /\ e \in Reach(session)
    /\ applied' = applied \cup {e}
    /\ UNCHANGED <<targets, session, edited, integrated>>

Done == applied = targets

Next ==
    \/ Edit \/ Integrate
    \/ \E e \in Envs : Apply(e)
    \/ (Done /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

\* Promise: after integration, the session can always place the change in
\* some environment it still has to update. Harm when broken: the session
\* ends with a target unplaced, and the owner must notice and relay it.
PlacementNeverStalls ==
    (integrated /\ ~Done) => \E e \in targets \ applied : e \in Reach(session)

\* Promise: no new session starts on ubuntu-26-development (2026-11-19).
\* Harm when broken: the owner has to notice in real time that the work must
\* move to Windows, which ADR 0001 removed.
NoNewSessionOnDevelopment == session # Dev
====
