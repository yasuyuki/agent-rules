---
name: phase-plan-documents
description: Write phase documents and acceptance criteria for long multi-phase work. Use when creating, updating or closing a phase plan, or when writing required acceptance conditions for a phase.
---

# Phase plan documents

The always-on `phased-plan-execution` rule decides when phases run. This skill
covers the documents that make them resumable.

## Location

Use the existing `<repo>/.claude/plan-phases/<slug>/`; when the repo itself is
`.claude`, use `<repo>/plan-phases/<slug>/`. Short work needs no phase document.

## Contents

Each phase document states the purpose, scope, required preconditions,
acceptance criteria and re-runnable validation commands. Name the host and cwd
whenever they are not obvious. Use existing tests and builds; a wrapper that
only shortens a command to one line, or an extra phase, adds nothing. Separate
what a machine can decide from what is still unverified.

## Required acceptance

Each required acceptance condition maps the executor, host/cwd, target
source/config, an entry that actually exists, required inputs, side effects and
the expected observation. For an entry adjacent to a forbidden operation, check
its internals. Separate existing preconditions, artifacts this work implements,
and unconfirmed items; a test of a new CLI is a post-implementation condition.
A pre-check entry that does not exist is never an existing smoke test.

## Closing

Cleaning up finished parts means deleting text that would mislead the next
resume decision and updating the needed references, nothing more. Write
durable procedures and design decisions into the owning README or docs once,
during the work. Keep resume information in the task Issue or work record, so a
temporary plan file is never its only home.
