---- MODULE ExecutionStop ----
\* One session of agent-environment hooks/execution_stop.py handle(), every
\* hook event of the current turn in every order. The Stop reviewer and the
\* follow-up classifier (stop_review.py) are free choices: each verdict or
\* transition is its own action. Line numbers refer to execution_stop.py.
EXTENDS Naturals

\* Mutation names a broken variant, "none" for the code. Race bounds Interrupts
\* that land while a Stop's reviewer runs. Prompts are distinct resumption
\* prompts; the hook compares their digests.
CONSTANTS Mutation, Race, Prompts

VARIABLES bound, active, interrupted, suspended, handoff, continuation,
          checkpoint, newTools, anyTools, resumed, managed, lastResume,
          turnOpen, out, ended, blockedNoTool, doubleBlock, userPaused,
          lost, raced

vars == <<bound, active, interrupted, suspended, handoff, continuation,
          checkpoint, newTools, anyTools, resumed, managed, lastResume,
          turnOpen, out, ended, blockedNoTool, doubleBlock, userPaused,
          lost, raced>>

\* The cache fields are the code's; the rest describe what the user did or saw:
\*   ended         how the user's current request ended (ghost)
\*   userPaused    the user interrupted or switched away and has not resumed (ghost)
\*   blockedNoTool the last demand had no tool run or fresh resumption after it (ghost)
\*   lost          this Stop's reviewer ran while an Interrupt landed (ghost)
TypeOK ==
  /\ {bound, active, interrupted, suspended, handoff, continuation, checkpoint,
      newTools, anyTools, resumed, managed, turnOpen, blockedNoTool, doubleBlock,
      userPaused, lost} \subseteq BOOLEAN
  /\ lastResume \in {0} \cup Prompts
  /\ out \in {"none", "context", "silent", "handoff", "reasonless", "demand", "cancelNotice"}
  /\ ended \in {"none", "complete", "unmanaged", "cancelled"}
  /\ raced \in 0..Race

Init ==
  /\ bound = FALSE /\ active = FALSE /\ interrupted = FALSE /\ suspended = FALSE
  /\ handoff = FALSE /\ continuation = FALSE /\ checkpoint = FALSE
  /\ newTools = FALSE /\ anyTools = FALSE /\ resumed = FALSE /\ managed = FALSE
  /\ lastResume = 0 /\ turnOpen = FALSE /\ out = "none" /\ ended = "none"
  /\ blockedNoTool = FALSE /\ doubleBlock = FALSE /\ userPaused = FALSE
  /\ lost = FALSE /\ raced = 0

\* new_request (L71-76); a new binding has an empty receipt directory.
StartRequest ==
  /\ bound' = TRUE /\ active' = TRUE /\ interrupted' = FALSE /\ suspended' = FALSE
  /\ handoff' = FALSE /\ continuation' = FALSE /\ checkpoint' = FALSE
  /\ newTools' = FALSE /\ anyTools' = FALSE /\ resumed' = FALSE /\ managed' = FALSE
  /\ lastResume' = 0 /\ turnOpen' = TRUE /\ out' = "context" /\ ended' = "none"
  /\ blockedNoTool' = FALSE /\ userPaused' = FALSE
  /\ UNCHANGED <<doubleBlock, lost, raced>>

\* ---------- the user: UserPromptSubmit and Interrupt ----------

\* L135-141, L153: a prompt with one Issue URL and no active request.
UserGivesIssue ==
  /\ ~turnOpen
  /\ ~bound \/ ~active
  /\ StartRequest

\* L172-173: the classifier says replace.
UserPointsToOtherIssue ==
  /\ ~turnOpen
  /\ bound /\ active
  /\ StartRequest

\* L135-139: no active request and no URL.
UserChats ==
  /\ ~turnOpen
  /\ ~bound \/ ~active
  /\ interrupted' = FALSE
  /\ turnOpen' = TRUE /\ out' = "none"
  /\ UNCHANGED <<bound, active, suspended, handoff, continuation, checkpoint,
                 newTools, anyTools, resumed, managed, lastResume, ended,
                 blockedNoTool, doubleBlock, userPaused, lost, raced>>

\* L177-179: the classifier says retain.
UserFollowsUp ==
  /\ ~turnOpen
  /\ bound /\ active
  /\ continuation' = FALSE
  /\ turnOpen' = TRUE /\ out' = "context"
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, checkpoint,
                 newTools, anyTools, resumed, managed, lastResume, ended,
                 blockedNoTool, doubleBlock, userPaused, lost, raced>>

\* L177-183: the classifier says resume; a repeated prompt is not fresh.
UserResumes ==
  /\ ~turnOpen
  /\ bound /\ active
  /\ \E p \in Prompts :
       LET fresh == (handoff \/ interrupted \/ suspended) /\ p # lastResume IN
       /\ resumed' = (resumed \/ fresh)
       /\ lastResume' = IF fresh THEN p ELSE lastResume
       /\ blockedNoTool' = (blockedNoTool /\ ~fresh)
  /\ interrupted' = FALSE /\ suspended' = FALSE /\ handoff' = FALSE
  /\ continuation' = FALSE /\ userPaused' = FALSE
  /\ turnOpen' = TRUE /\ out' = "context"
  /\ UNCHANGED <<bound, active, checkpoint, newTools, anyTools, managed, ended,
                 doubleBlock, lost, raced>>

\* L174-176: the classifier says suspend, or it failed (L163-166).
UserSwitchesTask ==
  /\ ~turnOpen
  /\ bound /\ active
  /\ suspended' = TRUE /\ continuation' = FALSE /\ resumed' = FALSE
  /\ handoff' = TRUE /\ userPaused' = TRUE
  /\ turnOpen' = TRUE /\ out' = "context"
  /\ UNCHANGED <<bound, active, interrupted, checkpoint, newTools, anyTools,
                 managed, lastResume, ended, blockedNoTool, doubleBlock, lost, raced>>

\* L167-171: the classifier says cancel.
UserCancels ==
  /\ ~turnOpen
  /\ bound /\ active
  /\ active' = IF Mutation = "cancel-keeps-active" THEN active ELSE FALSE
  /\ interrupted' = TRUE /\ continuation' = FALSE
  /\ handoff' = FALSE /\ ended' = "cancelled" /\ userPaused' = FALSE
  /\ turnOpen' = TRUE /\ out' = "none"
  /\ UNCHANGED <<bound, suspended, checkpoint, newTools, anyTools, resumed,
                 managed, lastResume, blockedNoTool, doubleBlock, lost, raced>>

\* L120-125: Interrupt for the cached turn.
UserInterrupts ==
  /\ turnOpen
  /\ IF bound
       THEN interrupted' = TRUE /\ resumed' = FALSE /\ handoff' = TRUE
       ELSE UNCHANGED <<interrupted, resumed, handoff>>
  /\ userPaused' = (userPaused \/ (bound /\ active))
  /\ turnOpen' = FALSE /\ out' = "none"
  /\ UNCHANGED <<bound, active, suspended, continuation, checkpoint, newTools,
                 anyTools, managed, lastResume, ended, blockedNoTool, doubleBlock,
                 lost, raced>>

\* ---------- the agent and the hook: PostToolUse and Stop ----------

\* L195-200: a receipt for the current binding.
ToolRuns ==
  /\ turnOpen
  /\ bound /\ ~suspended /\ active
  /\ newTools' = TRUE /\ anyTools' = TRUE /\ blockedNoTool' = FALSE
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, resumed, managed, lastResume, turnOpen, out, ended,
                 doubleBlock, userPaused, lost, raced>>

PausedAtStop == interrupted /\ Mutation # "stop-ignores-interrupt"

\* L188-191, L204: no request, suspended, or not active.
StopQuietly ==
  /\ turnOpen
  /\ ~bound \/ suspended \/ (~PausedAtStop /\ ~active)
  /\ turnOpen' = FALSE /\ out' = "silent"
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, newTools, anyTools, resumed, managed, lastResume,
                 ended, blockedNoTool, doubleBlock, userPaused, lost, raced>>

\* L202-203: an interrupted request stops with its cached handoff.
StopWhileInterrupted ==
  /\ turnOpen
  /\ bound /\ ~suspended /\ PausedAtStop
  /\ out' = IF handoff THEN "handoff" ELSE "reasonless"
  /\ turnOpen' = FALSE
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, newTools, anyTools, resumed, managed, lastResume,
                 ended, blockedNoTool, doubleBlock, userPaused, lost, raced>>

Ready ==
  /\ turnOpen
  /\ bound /\ ~suspended /\ ~PausedAtStop /\ active

\* L216-221: a demand was made and no receipt is new since.
StopNoNewEvidence ==
  /\ Ready
  /\ checkpoint /\ continuation /\ ~newTools
  /\ handoff' = TRUE /\ continuation' = FALSE /\ out' = "handoff" /\ turnOpen' = FALSE
  /\ UNCHANGED <<bound, active, interrupted, suspended, checkpoint, newTools,
                 anyTools, resumed, managed, lastResume, ended, blockedNoTool,
                 doubleBlock, userPaused, lost, raced>>

\* L222-267: the resolver and reviewer run, which takes seconds. When lost is
\* TRUE, an Interrupt for this turn wrote the cache meanwhile; this Stop then
\* writes back its own copy (write_state, L23-32), the turn has ended, and its
\* output is not shown.
Assess ==
  /\ Ready
  /\ ~(checkpoint /\ continuation /\ ~newTools)
  /\ \E l \in IF raced < Race THEN BOOLEAN ELSE {FALSE} :
       /\ lost' = l
       /\ raced' = raced + (IF l THEN 1 ELSE 0)
       /\ userPaused' = (userPaused \/ l)
  /\ resumed' = FALSE
  /\ checkpoint' = TRUE /\ newTools' = FALSE

Show(o, open) ==
  /\ out' = IF lost' THEN "none" ELSE o
  /\ turnOpen' = (open /\ ~lost')

HandOff ==
  /\ handoff' = TRUE /\ continuation' = FALSE /\ Show("handoff", FALSE)
  /\ managed' = TRUE
  /\ UNCHANGED <<bound, active, interrupted, suspended, anyTools, lastResume,
                 ended, blockedNoTool, doubleBlock>>

\* L268-279: continue with progress the hook accepts.
ReviewerContinueAccepted ==
  /\ Assess
  /\ resumed \/ ~checkpoint \/ newTools \/ Mutation = "trust-advanced"
  /\ continuation' = TRUE /\ Show("demand", TRUE) /\ managed' = TRUE
  /\ doubleBlock' = (doubleBlock \/ (blockedNoTool /\ ~lost'))
  /\ blockedNoTool' = ~lost'
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, anyTools,
                 lastResume, ended>>

\* L280-283: continue without accepted progress.
ReviewerContinueWithoutProgress == Assess /\ HandOff

\* L224-248, L280-283: the contract or the review fails, or says unverified.
ReviewerUnverified == Assess /\ HandOff

\* L289-291: stopped as blocked.
ReviewerBlocked == Assess /\ HandOff

\* L284-288: stopped as cancelled.
ReviewerCancelled ==
  /\ Assess
  /\ active' = FALSE /\ interrupted' = FALSE /\ continuation' = FALSE
  /\ handoff' = FALSE /\ Show("cancelNotice", FALSE) /\ ended' = "cancelled"
  /\ managed' = TRUE
  /\ UNCHANGED <<bound, suspended, anyTools, lastResume, blockedNoTool, doubleBlock>>

\* L292-298: complete, backed by some receipt (L251).
ReviewerComplete ==
  /\ Assess
  /\ anyTools \/ Mutation = "complete-without-receipts"
  /\ continuation' = FALSE /\ ended' = "complete"
  /\ active' = IF Mutation = "complete-keeps-active" THEN active ELSE FALSE
  /\ managed' = TRUE /\ Show("silent", FALSE)
  /\ UNCHANGED <<bound, interrupted, suspended, handoff, anyTools, lastResume,
                 blockedNoTool, doubleBlock>>

\* L251-256: complete with no receipt becomes unverified.
ReviewerCompleteWithoutEvidence ==
  /\ Assess
  /\ ~anyTools /\ Mutation # "complete-without-receipts"
  /\ HandOff

\* L292-298: unmanaged before any managed verdict.
ReviewerUnmanaged ==
  /\ Assess
  /\ ~managed
  /\ continuation' = FALSE /\ active' = FALSE /\ ended' = "unmanaged"
  /\ Show("silent", FALSE)
  /\ UNCHANGED <<bound, interrupted, suspended, handoff, anyTools, managed,
                 lastResume, blockedNoTool, doubleBlock>>

\* L257-262: unmanaged after a managed verdict becomes unverified.
ReviewerUnmanagedAfterWork ==
  /\ Assess
  /\ managed
  /\ HandOff

User ==
  \/ UserGivesIssue \/ UserPointsToOtherIssue \/ UserChats \/ UserFollowsUp
  \/ UserResumes \/ UserSwitchesTask \/ UserCancels \/ UserInterrupts

System ==
  \/ ToolRuns \/ StopQuietly \/ StopWhileInterrupted \/ StopNoNewEvidence
  \/ ReviewerContinueAccepted \/ ReviewerContinueWithoutProgress
  \/ ReviewerUnverified \/ ReviewerBlocked \/ ReviewerCancelled
  \/ ReviewerComplete \/ ReviewerCompleteWithoutEvidence
  \/ ReviewerUnmanaged \/ ReviewerUnmanagedAfterWork

Next == User \/ System

Spec == Init /\ [][Next]_vars

\* After the user interrupts or switches to another request, the hook never
\* tells the agent to keep working until the user resumes or starts a new one.
NoDemandWhilePaused == out = "demand" => ~userPaused

\* A request never ends as complete unless some tool observation backs it.
NoCompleteWithoutEvidence == ended = "complete" => anyTools

\* Two demands to keep working never come back to back without a tool run or
\* a fresh resumption between them.
NoRepeatedDemandWithoutEvidence == ~doubleBlock

\* A cancelled request is never told to keep working.
CancelledNeverContinues == ended = "cancelled" => out # "demand"

\* A request that is complete, cancelled or judged unmanaged is never handed
\* off as unfinished.
NoHandoffAfterFinish == out = "handoff" => ended = "none"

\* Every stop the hook shows the user says why it stopped.
EveryStopHasReason == out # "reasonless"
====
