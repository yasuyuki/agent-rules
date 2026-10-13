---
name: rule-experiment-role-gate
description: Role and phase boundaries for rule experiments. Use when working in a rule experiment apparatus or on an experiment phase, as controller or subject, or when changing the apparatus constitution.
---

# Rule experiment role gate

Read the executor in the phase metadata first.

1. The controller changes only the apparatus declaration files and never
   implements the subject workload.
2. The subject leaves variant source, measurement, constitution and review
   unchanged.
3. Nobody edits the baseline directly.
4. Launch through the apparatus entry, not a low-level launch wrapper.

The constitution is two peer documents, `CONSTITUTION.md` and
`docs/IMPROVEMENT-POLICY.md`. The first defines what the apparatus is; the
second defines how to reduce and improve it without losing its purpose. Read
both before changing the apparatus. Neither is removed as a reduction step; a
change to either is a deliberate decision to change the purpose or the
improvement order. The apparatus purpose stays with the apparatus and never
becomes another product's purpose.

When the work would cross a role or phase boundary, stop implementing, record
the state in the work record, and wait for the right executor's instruction.
