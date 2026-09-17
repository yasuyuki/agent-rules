---
name: optimize-agent-docs
description: Create or revise agent-facing rules, skills, instructions, and execution contracts by retaining decisions unavailable from code or help. Use for agent-facing portions of mixed documents, not human manuals.
license: MIT
---

# Optimize agent documentation

Identify the requested outcome and authorized edit scope. Preserve the document's
language. Inspect only relevant code, help, and existing authoritative documents
needed to decide what the agent cannot otherwise recover. Subtract explanations
already available there; if nothing necessary remains, omit the new document or
remove the redundant one within the authorized scope. Add a short index to a
concrete entry point only when it helps the agent find needed information.
If a requested new guide would only repeat supplied help, return that finding
and the existing help entry point rather than manufacturing a document to fill
the requested shape; respect an explicit requirement to retain a separate copy.

Keep the execution purpose, permission boundaries, environment selection,
unrecoverable current state, and acceptance conditions. Do not replace important
information unavailable from code or help with a reference the executing agent
cannot retrieve. Keep one editable authority; moving the same instructions to
another document is not a reduction.

For a necessary defense against serious failure, first consider enforcement in
the ordinary code path or platform. An optional helper, a test, or an instruction
to remember a check is not enforcement in that path. Preserve existing defenses:
assess the consequences without them before using current safety as grounds to
remove them. Lack of an observed failure does not establish that its preconditions
are impossible.

Do not add warnings or recurrence procedures for easily recoverable problems or
problems whose preconditions do not hold on the relevant path. Include human
monitoring, approval waits, and repeated work in recovery cost. This does not
cancel explicit requirements, necessary data protection, or authorization limits.

If a necessary protection can be implemented but implementation is outside the
request, return that concrete remaining change to the designated task or issue;
do not implement it without authorization or claim completion by relocating its
documentation. Retain the judgment that cannot be enforced in code.

Return a focused edit, deletion, or no change. Do not rewrite healthy sections or
create an audit report, new ledger, maintenance workflow, or numerical reduction
target. The result is the useful remainder, not a record of the optimization.
