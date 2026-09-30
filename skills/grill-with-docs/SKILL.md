---
name: grill-with-docs
description: A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go.
disable-model-invocation: true
---

Use both dependency skills, `grilling` and `domain-modeling`, in the same interview.

If the agent provides a native Skill tool, invoke both by name. Otherwise read
their `SKILL.md` files from the agent's skill catalog. They are also available
beside this skill as [grilling](../grilling/SKILL.md) and
[domain-modeling](../domain-modeling/SKILL.md). If either dependency is missing,
report the missing skill before starting the interview.

Follow `grilling` for questions and decisions. Apply `domain-modeling` as terms
and decisions are resolved. Before writing `CONTEXT.md`, read the dependency's
`CONTEXT-FORMAT.md`; the glossary contains only resolved vocabulary. Keep open
design questions in the conversation. Consult `ADR-FORMAT.md` when a decision
qualifies for an ADR. Respect the user's requested scope and existing authorization.
