---- MODULE ExecutionStopChart ----
EXTENDS ExecutionStop

ChartReview == StartStopReview /\ ~resumed /\ ~handoff
ChartInterrupt == UserInterrupts /\ active /\ ~resumed
ChartQuestion == UserFollowsUp /\ interrupted /\ out = "silent"
ChartCancel == UserCancels /\ handoff
ChartResume == UserResumes /\ interrupted /\ out = "handoff"
ChartDone == resumed /\ UNCHANGED vars

ChartNext ==
  \/ UserGivesIssue \/ ChartReview \/ ReviewerBlocked \/ ChartInterrupt
  \/ InterruptDuringReview \/ DiscardStopReview \/ ChartQuestion
  \/ StopWhileInterrupted \/ ChartCancel \/ StopQuietly \/ ChartResume \/ ChartDone

ChartSpec == Init /\ [][ChartNext]_vars
====
