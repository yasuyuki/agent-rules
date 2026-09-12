---
name: human-handoff
description: Read before presenting commands or steps for the user to execute, including explicit requests for a command, launch instructions, or a copy-paste answer. Also use for requests for user input, physical actions, or approval. Make the remaining human action reliable to carry out.
---

# Handing work to a human

Apply this skill even when the user asks only for a command and no "please run"
or handoff heading is needed. A request for instructions is not authorization to
perform the requested action instead of showing it.

Finish the authorized machine work before handing over the part that requires
the person. Use available tools to resolve facts and routine choices yourself.
Check a plausible CLI or API when it could remove a manual step; do not broaden
the task into installing tools, changing permissions, or handling credentials
just to avoid asking. Respect sandbox and authorization boundaries.

Ask only for missing input that materially affects the result, required approval,
or an action the available tools cannot perform. Existing authorization remains
valid; do not ask for it again. Continue independent work while waiting.

Give the smallest remaining action, its execution context, and what success
looks like. Start from the person's current host and screen, using available
evidence and existing entry-point documentation. Do not assume a target input
field or terminal is already open: include the steps to open the application,
connect to the target environment, and reach the input, as needed, in execution
order with the visible success state for each step. Reuse an already open,
connected session instead of restarting it. If the starting state is unknown,
make those setup steps conditional; ask only when the uncertainty prevents a
usable handoff. Distinguish checking the written procedure from observing the
actual screen or successfully completing the action.

Commands must survive the actual display and copy-paste path, not
merely parse as the original text. Console or harness wrapping can insert real
whitespace, even inside a quoted argument: `workspace-write` can become
`workspace- write`. A fenced one-line command alone does not prevent this.

When a command is long or the user reports wrapping, split it at syntactically
valid boundaries. Prefer existing short entrypoints, entering the target shell
and directory first, or native argument arrays with separate short elements.
Keep each option, path, and quoted value intact. Include the full WSL/SSH/container
prefix when assessing length. Do not rely on backslash/backtick continuations or
ask the user to repair wrapped text. Check the longest displayed line against
the known display constraint; if the width is unknown, shorten the invocation
without inventing a universal width guarantee.

When the remaining procedure amounts to a script (for example, checks sharing
variables, branching, or coordinated failure handling), reuse an existing entry
point or save and validate a script file before handing it over. Do not present
the script body as a copy-paste procedure, including a heredoc or encoded payload
that makes the user recreate the file. Keep ordinary short commands as commands.
Create a script only when needed and allowed; respect a no-new-scripts request.

Put the file where the intended user can access it within existing permissions.
If transfer is needed, provide a way to retrieve just that file, using a fixed
revision when retrieving from a repository, followed by a separate short execution
command. Do not require a repository clone just to obtain the script or pipe a
download directly into a shell. Verify the saved file, the available retrieval
path, and the target shell; state the working directory, success output and
failure behavior. Distinguish a validated handoff from execution by its recipient.

As soon as this need arises, analyze why the work requires a script-like human
handoff and whether an existing entry point can remove it. Separate observed
failures from suspected causes. If the need is likely to recur, find and update
the relevant existing issue or register one in the project's established issue
tracker. Record the symptom, affected entry point, reproduction conditions and
reason recurrence is expected; distinguish the immediate handoff workaround from
the unresolved cause. Do not wait for another failure, duplicate an existing
issue, or expand the task into fixing the underlying interface without authority.
If issue registration is unavailable, preserve the pending registration in the
existing handoff record and report the limitation.

Validate the exact presented syntax in the stated shell and use a safe dry run
or version query through the same argument path where available. Syntax checks
do not prove that copying from the UI preserves bytes. Never execute a destructive
or externally visible action merely to test the user's command.

If a result is needed, ask for the specific non-sensitive output or pass/fail.
Never request tokens, passwords, or private data in chat. Follow the applicable
`session-end-user-work` rule for final-response formatting.
