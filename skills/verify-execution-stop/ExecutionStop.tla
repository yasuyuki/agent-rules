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
          review, raced

vars == <<bound, active, interrupted, suspended, handoff, continuation,
          checkpoint, newTools, anyTools, resumed, managed, lastResume,
          turnOpen, out, ended, blockedNoTool, doubleBlock, userPaused,
          review, raced>>

\* The cache fields are the code's; the rest describe what the user did or saw:
\*   ended         how the user's current request ended (ghost)
\*   userPaused    the user interrupted or switched away and has not resumed (ghost)
\*   blockedNoTool the last demand had no tool run or fresh resumption after it (ghost)
\* review holds the part of the pre-review cache the verdict branches still
\* need. The remaining cache fields are stable while the review runs.
ReviewSnapshot(phase, wasInterrupted, wasResumed, hadHandoff) ==
  [phase |-> phase, interrupted |-> wasInterrupted, resumed |-> wasResumed,
   handoff |-> hadHandoff]

IdleReview == ReviewSnapshot("idle", FALSE, FALSE, FALSE)
ReviewIdle == review.phase = "idle"

TypeOK ==
  /\ {bound, active, interrupted, suspended, handoff, continuation, checkpoint,
      newTools, anyTools, resumed, managed, turnOpen, blockedNoTool, doubleBlock,
      userPaused} \subseteq BOOLEAN
  /\ lastResume \in {0} \cup Prompts
  /\ out \in {"none", "context", "silent", "handoff", "reasonless", "demand", "cancelNotice"}
  /\ ended \in {"none", "complete", "unmanaged", "cancelled"}
  /\ review \in [phase : {"idle", "working", "interrupted"}, interrupted : BOOLEAN,
                 resumed : BOOLEAN, handoff : BOOLEAN]
  /\ raced \in 0..Race

Init ==
  /\ bound = FALSE /\ active = FALSE /\ interrupted = FALSE /\ suspended = FALSE
  /\ handoff = FALSE /\ continuation = FALSE /\ checkpoint = FALSE
  /\ newTools = FALSE /\ anyTools = FALSE /\ resumed = FALSE /\ managed = FALSE
  /\ lastResume = 0 /\ turnOpen = FALSE /\ out = "none" /\ ended = "none"
  /\ blockedNoTool = FALSE /\ doubleBlock = FALSE /\ userPaused = FALSE
  /\ review = IdleReview /\ raced = 0

\* new_request (L102-107); a new binding has an empty receipt directory.
StartRequest ==
  /\ bound' = TRUE /\ active' = TRUE /\ interrupted' = FALSE /\ suspended' = FALSE
  /\ handoff' = FALSE /\ continuation' = FALSE /\ checkpoint' = FALSE
  /\ newTools' = FALSE /\ anyTools' = FALSE /\ resumed' = FALSE /\ managed' = FALSE
  /\ lastResume' = 0 /\ turnOpen' = TRUE /\ out' = "context" /\ ended' = "none"
  /\ blockedNoTool' = FALSE /\ userPaused' = FALSE
  /\ UNCHANGED <<doubleBlock, review, raced>>

\* ---------- the user: UserPromptSubmit and Interrupt ----------

\* L173-190: a prompt with one Issue URL and no active request.
UserGivesIssue ==
  /\ ReviewIdle /\ ~turnOpen
  /\ ~bound \/ ~active
  /\ StartRequest

\* L209-210: the classifier says replace.
UserPointsToOtherIssue ==
  /\ ReviewIdle /\ ~turnOpen
  /\ bound /\ active
  /\ StartRequest

\* L173-177: no active request and no URL.
UserChats ==
  /\ ReviewIdle /\ ~turnOpen
  /\ ~bound \/ ~active
  /\ interrupted' = FALSE
  /\ turnOpen' = TRUE /\ out' = "none"
  /\ UNCHANGED <<bound, active, suspended, handoff, continuation, checkpoint,
                 newTools, anyTools, resumed, managed, lastResume, ended,
                 blockedNoTool, doubleBlock, userPaused, review, raced>>

\* L214-216: the classifier says retain.
UserFollowsUp ==
  /\ ReviewIdle /\ ~turnOpen
  /\ bound /\ active
  /\ continuation' = FALSE
  /\ turnOpen' = TRUE /\ out' = "context"
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, checkpoint,
                 newTools, anyTools, resumed, managed, lastResume, ended,
                 blockedNoTool, doubleBlock, userPaused, review, raced>>

\* L214-220: the classifier says resume; a repeated prompt is not fresh.
UserResumes ==
  /\ ReviewIdle /\ ~turnOpen
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
                 doubleBlock, review, raced>>

\* L211-213: the classifier says suspend, or it failed (L201-203).
UserSwitchesTask ==
  /\ ReviewIdle /\ ~turnOpen
  /\ bound /\ active
  /\ suspended' = TRUE /\ continuation' = FALSE /\ resumed' = FALSE
  /\ handoff' = TRUE /\ userPaused' = TRUE
  /\ turnOpen' = TRUE /\ out' = "context"
  /\ UNCHANGED <<bound, active, interrupted, checkpoint, newTools, anyTools,
                 managed, lastResume, ended, blockedNoTool, doubleBlock, review, raced>>

\* L204-208: the classifier says cancel.
UserCancels ==
  /\ ReviewIdle /\ ~turnOpen
  /\ bound /\ active
  /\ active' = IF Mutation = "cancel-keeps-active" THEN active ELSE FALSE
  /\ interrupted' = (Mutation = "cancel-looks-interrupted") /\ continuation' = FALSE
  /\ handoff' = FALSE /\ ended' = "cancelled" /\ userPaused' = FALSE
  /\ turnOpen' = TRUE /\ out' = "none"
  /\ UNCHANGED <<bound, suspended, checkpoint, newTools, anyTools, resumed,
                 managed, lastResume, blockedNoTool, doubleBlock, review, raced>>

\* L148-152: Interrupt for the cached turn.
UserInterrupts ==
  /\ ReviewIdle /\ turnOpen
  /\ IF bound /\ active
       THEN interrupted' = TRUE /\ resumed' = FALSE /\ handoff' = TRUE
       ELSE UNCHANGED <<interrupted, resumed, handoff>>
  /\ userPaused' = (userPaused \/ (bound /\ active))
  /\ turnOpen' = FALSE /\ out' = "none"
  /\ UNCHANGED <<bound, active, suspended, continuation, checkpoint, newTools,
                 anyTools, managed, lastResume, ended, blockedNoTool, doubleBlock,
                 review, raced>>

\* ---------- the agent and the hook: PostToolUse and Stop ----------

\* L234-238: a receipt for the current binding.
ToolRuns ==
  /\ ReviewIdle /\ turnOpen
  /\ bound /\ ~suspended /\ active
  /\ newTools' = TRUE /\ anyTools' = TRUE /\ blockedNoTool' = FALSE
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, resumed, managed, lastResume, turnOpen, out, ended,
                 doubleBlock, userPaused, review, raced>>

PausedAtStop ==
  /\ interrupted /\ Mutation # "stop-ignores-interrupt"
  /\ active \/ Mutation = "cancel-looks-interrupted"

\* L225-232: no request, suspended, or not active.
StopQuietly ==
  /\ ReviewIdle /\ turnOpen
  /\ ~bound \/ suspended \/ (~PausedAtStop /\ ~active)
  /\ turnOpen' = FALSE /\ out' = "silent"
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, newTools, anyTools, resumed, managed, lastResume,
                 ended, blockedNoTool, doubleBlock, userPaused, review, raced>>

\* L239-240: an interrupted request stops with its cached handoff.
StopWhileInterrupted ==
  /\ ReviewIdle /\ turnOpen
  /\ bound /\ ~suspended /\ PausedAtStop
  /\ out' = IF handoff THEN "handoff" ELSE "reasonless"
  /\ turnOpen' = FALSE
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, newTools, anyTools, resumed, managed, lastResume,
                 ended, blockedNoTool, doubleBlock, userPaused, review, raced>>

Ready ==
  /\ ReviewIdle /\ turnOpen
  /\ bound /\ ~suspended /\ ~PausedAtStop /\ active

\* L260-261: a demand was made and no receipt is new since.
StopNoNewEvidence ==
  /\ Ready
  /\ checkpoint /\ continuation /\ ~newTools
  /\ handoff' = TRUE /\ continuation' = FALSE /\ out' = "handoff" /\ turnOpen' = FALSE
  /\ UNCHANGED <<bound, active, interrupted, suspended, checkpoint, newTools,
                 anyTools, resumed, managed, lastResume, ended, blockedNoTool,
                 doubleBlock, userPaused, review, raced>>

\* L141-144, L241, L262-288: the review runs on the cache read at Stop.
StartStopReview ==
  /\ Ready
  /\ ~(checkpoint /\ continuation /\ ~newTools)
  /\ review' = ReviewSnapshot("working", interrupted, resumed, handoff)
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, newTools, anyTools, resumed, managed, lastResume,
                 turnOpen, out, ended, blockedNoTool, doubleBlock, userPaused, raced>>

\* L148-152: Interrupt publishes a newer cache while the review is outside the lock.
InterruptDuringReview ==
  /\ review.phase = "working" /\ raced < Race
  /\ interrupted' = TRUE /\ resumed' = FALSE /\ handoff' = TRUE
  /\ turnOpen' = FALSE /\ out' = "none" /\ userPaused' = TRUE
  /\ review' = [review EXCEPT !.phase = "interrupted"]
  /\ raced' = raced + 1
  /\ UNCHANGED <<bound, active, suspended, continuation, checkpoint, newTools,
                 anyTools, managed, lastResume, ended, blockedNoTool, doubleBlock>>

\* L242-245: a changed cache discards the assessment and its response.
DiscardStopReview ==
  /\ review.phase = "interrupted" /\ Mutation # "review-overwrites-interrupt"
  /\ review' = IdleReview /\ out' = "silent"
  /\ UNCHANGED <<bound, active, interrupted, suspended, handoff, continuation,
                 checkpoint, newTools, anyTools, resumed, managed, lastResume,
                 turnOpen, ended, blockedNoTool, doubleBlock, userPaused, raced>>

ReviewWasInterrupted == review.phase = "interrupted"

Assess ==
  /\ review.phase = "working" \/ (ReviewWasInterrupted /\ Mutation = "review-overwrites-interrupt")
  /\ review' = IdleReview /\ UNCHANGED <<raced, userPaused>>
  /\ resumed' = FALSE
  /\ checkpoint' = TRUE /\ newTools' = FALSE

Show(result, open) ==
  /\ out' = IF ReviewWasInterrupted THEN "none" ELSE result
  /\ turnOpen' = (open /\ ~ReviewWasInterrupted)

HandOff ==
  /\ handoff' = TRUE /\ continuation' = FALSE /\ Show("handoff", FALSE)
  /\ managed' = TRUE /\ interrupted' = review.interrupted
  /\ UNCHANGED <<bound, active, suspended, anyTools, lastResume,
                 ended, blockedNoTool, doubleBlock>>

\* L308-318: continue with progress the hook accepts.
ReviewerContinueAccepted ==
  /\ Assess
  /\ review.resumed \/ ~checkpoint \/ newTools \/ Mutation = "trust-advanced"
  /\ continuation' = TRUE /\ Show("demand", TRUE) /\ managed' = TRUE
  /\ doubleBlock' = (doubleBlock \/ (blockedNoTool /\ ~ReviewWasInterrupted))
  /\ blockedNoTool' = ~ReviewWasInterrupted
  /\ interrupted' = review.interrupted /\ handoff' = review.handoff
  /\ UNCHANGED <<bound, active, suspended, anyTools, lastResume, ended>>

\* L319-320: continue without accepted progress.
ReviewerContinueWithoutProgress == Assess /\ HandOff

\* L262-288, L319-320: the contract or the review fails, or says unverified.
ReviewerUnverified == Assess /\ HandOff

\* L325: stopped as blocked.
ReviewerBlocked == Assess /\ HandOff

\* L321-324: stopped as cancelled.
ReviewerCancelled ==
  /\ Assess
  /\ active' = FALSE /\ interrupted' = FALSE /\ continuation' = FALSE
  /\ handoff' = FALSE /\ Show("cancelNotice", FALSE) /\ ended' = "cancelled"
  /\ managed' = TRUE
  /\ UNCHANGED <<bound, suspended, anyTools, lastResume, blockedNoTool, doubleBlock>>

\* L326-331: complete, backed by some receipt (L291).
ReviewerComplete ==
  /\ Assess
  /\ anyTools \/ Mutation = "complete-without-receipts"
  /\ continuation' = FALSE /\ ended' = "complete"
  /\ active' = IF Mutation = "complete-keeps-active" THEN active ELSE FALSE
  /\ managed' = TRUE /\ Show("silent", FALSE)
  /\ interrupted' = review.interrupted /\ handoff' = review.handoff
  /\ UNCHANGED <<bound, suspended, anyTools, lastResume, blockedNoTool, doubleBlock>>

\* L291-296: complete with no receipt becomes unverified.
ReviewerCompleteWithoutEvidence ==
  /\ Assess
  /\ ~anyTools /\ Mutation # "complete-without-receipts"
  /\ HandOff

\* L326-331: unmanaged before any managed verdict.
ReviewerUnmanaged ==
  /\ Assess
  /\ ~managed
  /\ continuation' = FALSE /\ active' = FALSE /\ ended' = "unmanaged"
  /\ Show("silent", FALSE)
  /\ interrupted' = review.interrupted /\ handoff' = review.handoff
  /\ UNCHANGED <<bound, suspended, anyTools, managed, lastResume,
                 blockedNoTool, doubleBlock>>

\* L297-302: unmanaged after a managed verdict becomes unverified.
ReviewerUnmanagedAfterWork ==
  /\ Assess
  /\ managed
  /\ HandOff

User ==
  \/ UserGivesIssue \/ UserPointsToOtherIssue \/ UserChats \/ UserFollowsUp
  \/ UserResumes \/ UserSwitchesTask \/ UserCancels \/ UserInterrupts

System ==
  \/ ToolRuns \/ StopQuietly \/ StopWhileInterrupted \/ StopNoNewEvidence
  \/ StartStopReview \/ InterruptDuringReview \/ DiscardStopReview
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
