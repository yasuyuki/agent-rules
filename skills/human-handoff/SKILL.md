---
name: human-handoff
description: Reduce unavoidable manual work to a clear, actionable request when a task needs user input, a physical action, or approval.
---

# Handing work to a human

Finish the authorized machine work before handing over the part that requires
the person. Use available tools to resolve facts and routine choices yourself.
Check a plausible CLI or API when it could remove a manual step; do not broaden
the task into installing tools, changing permissions, or handling credentials
just to avoid asking. Respect sandbox and authorization boundaries.

Ask only for missing input that materially affects the result, required approval,
or an action the available tools cannot perform. Existing authorization remains
valid; do not ask for it again. Continue independent work while waiting.

Give the smallest remaining action, its execution context, and what success
looks like. Commands should be directly copyable. Use a script when quoting or
multiple dependent operations make it more reliable, not to satisfy a character
limit. Validate syntax or use a safe dry run where available; never execute a
destructive or externally visible action merely to test the user's command.

If a result is needed, ask for the specific non-sensitive output or pass/fail.
Never request tokens, passwords, or private data in chat. Follow the applicable
`session-end-user-work` rule for final-response formatting.
