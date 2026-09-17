---
name: optimize-human-docs
description: Create or revise human-facing READMEs, manuals, and procedures around the reader's decisions and actions, removing unnecessary explanation while preserving usable conditions. Use for human-facing portions of mixed documents, not agent execution rules.
license: MIT
---

# Optimize human documentation

Identify what the reader needs to decide or do from the request and available
document. Preserve its language. Read relevant source or help only when needed
to resolve a factual claim; sufficient supplied information needs no extra
questions or investigation.

Keep a README as an entry point: purpose, shortest usable start, and links to
needed detail. Put necessary goal-oriented explanations in the appropriate
manual, reusing an existing one when possible. A procedure needs an identifiable
target, separately testable prerequisites, ordered actions, and observable
success. Do not assume the reader has the original conversation.

Remove redundant background, equivalent statements, and branches the reader
does not need. Preserve the conditions that distinguish targets or outcomes:
packing several prerequisites into one sentence, replacing concrete objects with
vague nouns, or inventing a path is not simplification. Resolve unknowns from
available evidence; leave a material gap explicit or ask for the missing fact
instead of making it up.

Retain explanations that help a person choose and use a feature even when its
implementation is readable. For specification values, arguments, and defaults,
refer to the accessible authoritative source or help instead of maintaining a
second handwritten catalogue. Keep enough context to make the reference useful.

Return the smallest sufficient document change, or no change when the document
already serves its reader. Do not add a document, report, template, or word-count
target merely to show work. A documentation request does not authorize executing
the documented operations. When actually handing work to a person and
`human-handoff` is available, use it for the handoff details; its absence does
not prevent this document edit.
