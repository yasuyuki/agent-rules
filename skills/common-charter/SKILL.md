---
name: common-charter
description: Charter shared by every product and environment repository the owner manages. Read before changing a product's API, CLI, configuration, behaviour, persistent data format, normal entry point or the rules that govern them, and before weighing user waiting, time, cost or resources in a design or an acceptance.
---

# Common charter

This charter is the single source of the norms that every product and
environment repository under this management shares. A repository's own
charter or standards define its purpose and boundaries and may add
requirements. They do not relax this charter or keep a second copy of it.
Applying this charter never moves another product's implementation,
migration or lifecycle into a repository that does not own it.

## Compatibility and data migration

A product does not have to stay compatible with its current version when it
is revised. Breaking changes to APIs, CLIs, configuration, behaviour and
storage formats are allowed. Do not keep aliases, compatibility layers, old
branches, or duplicate implementations and reads or writes only for
compatibility with an earlier version. This does not require breaking
compatibility or deleting a working feature without a purpose.

When stored data becomes incompatible, support only a forward conversion from
the immediately preceding data-format generation to the new current format.
A generation is an incompatible boundary in the persistent data format. It
is not counted per release, patch or commit that keeps the format. Identify
the format with the product's existing mechanism. With current format N,
provide the conversion from N-1 to N, and move the target up at the next
incompatible generation. Direct or chained migration from N-2 or older,
reverse conversion, and old-version reads, writes or downgrades are not
supported, and past converters are not accumulated and maintained. A change
that keeps the storage format compatible gets no conversion.

Dropping compatibility is not permission to destroy existing assets. Keep the
user data that must carry over, and keep the original recoverable until the
conversion is confirmed. For a failed conversion, corruption, an unsupported
old generation or an unknown newer format, report the reason and the
supported range, and never overwrite the original with valid empty data.
Keeping the original does not promise that the current product can read or
convert an unsupported format. Derived data that can be regenerated safely
may be regenerated under the existing protection and use conditions. Do not
treat irreplaceable manual data as regenerable.

Keep the current supported configuration working, along with safety,
permissions, evidence authenticity and any identity a product guarantees. Do
not bypass a running contract or rewrite past results. When a saved record is
read in a later format, keep the original record distinct from the converted
representation and do not change past verdicts or authority retroactively.

## Transparent normal operation

Transparent normal operation is a required quality. A human or a controller
agent gives only the goal and the necessary choices, and uses a short normal
path that keeps the necessary safety checks without knowing the internal
structure. Keep first-time setup, migration, and incident diagnosis and repair
apart from normal use, and do not make their procedures a prerequisite of
every run.

The layer that owns each responsibility resolves routine state, builds launch
arguments, runs mechanical consistency checks and keeps the necessary
records. Do not make humans or controller agents routinely walk several
histories, assemble environment-specific arguments, reinterpret or re-explain
the same premise, or copy the same fact into several places. Pass working
context centred on the current target and state, and keep related
specifications, history and evidence available on demand.

Hiding output, loading the whole history, or handing the work to another
agent does not make an operation transparent. Prefer existing entry points,
declarations and records, and remove unnecessary processing and repeated
cognitive load. Keep the necessary permissions and explicit approvals, the
current invariants, revalidation after a relevant state change, and judgement
of semantic validity at the operations they protect. Revise an unnecessary
requirement through a deliberate contract change. When the target, source or
authority is ambiguous, do not guess. Report the problem and the needed
action at the affected operation, and do not run a change that cannot be
confirmed safe.

Apply this quality to the design, implementation and acceptance of the
system. Do not implement it as a new per-task declaration, checklist or
duplicate evidence. Do not use it as a reason to move a responsibility into a
layer that does not own it. Improve the layer that owns it.

## User waiting and resource limits

Meet the necessary safety and quality requirements, then weigh time, cost,
rework and user burden against the actual operating decision. Do not require
every measured indicator to improve at once. An authorized, proportionate cost
increase may be acceptable for a useful reduction in time or burden. That is
not permission to exceed resource limits or to ignore a required quality
regression. Keep supporting measurements apart from criteria required for
acceptance, and do not change a fixed evaluation after seeing results to
favour a candidate.

Repair, evidence organization and measurement are supporting work. Return
their findings to the original decision: what is now supported, what remains
unresolved, and which specific missing evidence could change the choice.
Finishing supporting work does not finish the decision.

Assume that the user will not wait and is not willing to wait. Avoidable
waiting, monitoring and repeated intervention are usability defects even
when an operation eventually succeeds. Do not require the user to restate
this assumption or to set a time budget for every task. Keeping first-time
setup and repair apart from routine use does not exempt them from reducing
avoidable waiting.

Start from the ideal path with no avoidable user waiting. Remove unnecessary
work and dependencies before accelerating the steps that remain. Within the
required quality, safety, approvals, and cost and resource limits, reduce both
the elapsed time from the user's request to a usable result and the time
during which the user is blocked from useful work. Speed is not an unlimited
spending mandate. An early acknowledgement or returning control is not
acceptance.

For an operation that is irreducibly long, minimize the necessary blocking and
let genuinely independent work proceed. Use existing execution and
result-retrieval paths so that the user does not poll, reconstruct state, or
come back to advance mechanical steps. Submission is not completion, and
deferred work that still blocks the requested result is not eliminated
waiting.

Choose a latency target that fits the operation when you improve a path,
instead of accepting its current duration as necessary. Apply established
budgets and resource allowances alongside these targets. Judge the path with
representative observations and reusable evidence, and state unavoidable
waits and any timing exclusions. Numeric limits belong to the affected
operation or an approved operating profile, not to a universal threshold
here.

Additional spend or scarce usage is justified only by a meaningful,
proportionate reduction in time to a usable result or in user burden, and it
stays within authorized limits. Budget headroom is not a target to consume.
Evaluate total resources across preparation, management, handoffs,
implementation, review, retries, validation and result delivery, not only one
model's unit price or one stage's duration. Include one-time improvement
effort and realistic recurring costs where they affect the decision.
Distinguish reference cost estimates, actual charges, and consumption of
limited usage allowances. A missing measurement is not zero cost.

Reuse established budgets, approved operating profiles and available
evidence. An instruction to be fast does not authorize materially higher
spending, greater usage, premium tiers, extra agents or speculative duplicate
runs. When existing authorization does not cover a material increase, use an
authorized lower-resource path that meets the requirements, or state the
specific trade-off before incurring the increase. Routine actions already
within authorization need no new budget question. If the latency target cannot
be met within the applicable limits, report the unmet target instead of
silently exceeding a limit or declaring acceptance.

Keep the necessary protections and approvals, evidence integrity and
responsibility boundaries. Speed and deferral never relabel pending required
validation as completed, and incomplete supporting diagnostics never block
unrelated safe analysis or result delivery. Do not add orchestration or
budget-management layers, per-task checklists, cost reports or duplicate
records only to assert this principle.

## Normal-path acceptance

When you change a normal entry point or the rules that govern it, check the
affected path with representative use after first-time setup. Humans should
not need to reconstruct environment-specific commands. Controller agents
should not need to rebuild routine state from several histories or repeatedly
explain the same mechanical checks. Keep task-relevant specifications and
evidence available on demand.

Apply the currently effective contract at the operations it protects,
including revalidation after a relevant state change. Unrelated diagnostics
do not become blanket prerequisites. Keep first-time setup, migration
inventories and incident repair apart from routine use.

Use existing tests and evidence where possible. These are acceptance criteria
for system changes, not new per-task gates, declarations, reports or review
records. Judge reductions in repeated work, time to a usable result and user
blocking within the applicable cost and resource limits. Hidden output, an
early acknowledgement, work moved to another agent, or an unaccounted
resource increase is not sufficient.

Check that the affected path returns usable evidence, a bounded conclusion and
the next decision without avoidable repair or repetition. A documented
uncertainty, a rejected candidate or a bounded inconclusive result can be a
valid return. Do not encode this charter's prose as mandatory string matches.
