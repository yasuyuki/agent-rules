---
name: git-topic-lifecycle
description: Sync, hand over, clean up and retire a registered task topic. Use when merging a same-name remote topic, passing a topic to another clone or host, resolving dirty state before finishing, or retiring a checkout.
---

# Git topic lifecycle

The always-on `git-branch-management` rule owns task identity and integration.
This skill covers the conditional operations on an existing topic. Operation
syntax comes from the adopted `workspace-lifecycle` CLI help.

## Ownership while integrating

While the lead fixes the merge, validation, commit and push set, assign the
changed ranges and stop conflicting file updates. One updater owns a remote
topic at a time, across clones and hosts. Record the owner and the saved commit
in the existing task or Issue; the successor fetches that remote and resumes.
A local lease or Git lock is not cross-host exclusion. Leave other checkouts on
their branches and keep one branch per task, not per agent or per sync.

## Same-name remote sync

Taking in the same-name remote is a sync of the same task. It neither accepts
nor integrates another task. Merge normally through the operation owner's entry
for the confirmed repo, destination and scope, and resolve conflicts or
interrupted operations in the same task. Keep the original commits and finished
preservation steps. When HEAD changes, validate again on that HEAD; earlier
validation never accepts a new HEAD, and a sync alone never marks work
accepted, integrated or retirable. Push follows the shared preflight. Resume by
the same task, not by repointing to another source, discarding intent or
recommitting the same change.

A shared integration branch receives accepted results only; it is never another
task's development branch. Resolve conflicts, failed validation and interrupts
on the same target and state, without new branches or history rewrites.

## Dirty state

Resolve regenerable owned outputs after checking their provenance. Save unique
information to an approved separate store and read it back before touching the
original. Leave dirty state only when every applicable alternative is confirmed
to cause unrecoverable harm; record the reason, owner and next operation in the
task. Unknown ownership or effort is not irreversible harm.

## Retiring a checkout

Retire only after confirming preservation, actual integration, target identity
and the end of external use. Keep unintegrated work, registrations referenced as
a dependency or integration destination, the repository itself, hook sources
and runtimes. Keep usage leases distinct from Git administrative locks. Confirm
both the checkout and its registration are gone. Retire itself keeps the branch
and commits; deleting an integrated topic branch afterwards is decided only by
an environment's explicit cleanup policy, never by retire or this skill. Use the
normal retire entry; forced deletion, unconditional unlock,
hand-edited ledgers, bulk integration of all branches and scheduled sweeps are
outside it.

Direct Git operations and forced termination can bypass the lifecycle CLI, so
check actual Git state rather than assuming the CLI saw every change.
