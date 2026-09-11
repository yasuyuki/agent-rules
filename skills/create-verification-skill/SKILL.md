---
name: create-verification-skill
description: Create or update a project-specific skill that verifies real user behavior with evidence. Use when asked to generate or revise verification procedures, not for an ordinary verification run.
license: MIT; see LICENSE.txt and references/sources.md.
---

# Create a verification skill

Produce a skill another agent can use without this conversation to exercise a
project through a real user entry point, judge the result, retain evidence and
clean up. Read this file by path or use the host agent's optional skill command.
No particular agent API, installer, other skill, or agent-rules runtime is needed.

Generation and execution are separate requests. An ordinary request to verify
an app uses its existing verification skill; it does not authorize regenerating
it. If generation was not requested, leave source and registration unchanged.

## Discover and choose the proof

Read the target's instructions, README, existing source/placement configuration,
and relevant acceptance tests. Determine the canonical skill source, update
route and existing comparable skills before creating anything. Reuse a suitable
skill or extend the requested part. Never edit a managed distribution copy.

State the deliverable, destination and smallest meaningful feature/entry point
to prove. Discover from the actual project:

- **Launch:** documented command, build/runtime requirements and readiness signal.
- **Drive:** user's CLI/API/UI path and existing means of operating it. Inspect
  the actual command/selector/endpoint before writing an executable recipe.
- **Observe:** response, visible state, generated contents and required persistent
  side effects; locate the specification or existing contract for each assertion.
- **Isolate:** disposable data/config/profile/ports and ownership of processes.
  Inspect side effects even for a command called dry-run or test mode.

Choose one substantive feature first. A help screen, successful build, health
check or passing unit suite is preparation, not proof of that feature. Document
other known entry points as not-run; one surface's success proves only that
surface. Avoid a full feature inventory before the first proof.

Use existing build, operation and observation tools. Add a small project-specific
helper only when it prevents unreliable repetition or supplies missing evidence;
do not build a generic repo analyzer, generation service or control platform.
Fix a startup problem only within the authorized scope. Missing permission,
dependency or safe isolation is blocked, with the unmet prerequisite recorded.

## Write a candidate, preserving existing work

Use the project's source convention, not an agent-specific hardcoded directory.
For a managed environment, change the canonical source and use its existing
placement mechanism after proof. Agent-specific registration belongs in that
mechanism, not the shared skill. If no convention exists, choose a repository
directory agreed with the task's scope and document path-based invocation.

Inventory destination files before writing. If a hand-written/unowned skill or
unrelated file occupies the destination, leave it intact; select an unused name
or report the collision if the requested name is fixed. On an authorized update,
keep the verified version usable while creating a separate draft candidate.
Limit replacement to identified owned files after the candidate passes; preserve
hand-written additions. Do not treat a matching directory name as ownership.

Use standard YAML frontmatter with `name` matching the directory and a specific
`description`. Keep references relative to the skill and resolve the project
root from documented configuration or an explicit argument. Do not embed the
author's HOME, machine paths or required vendor tool names. App OS/runtime/harness
requirements are legitimate; record them separately from agent compatibility.

The generated SKILL.md must give executable, complete instructions for:

| Part | Required contract |
| --- | --- |
| Launch | Exact preparation/launch commands, cwd, dependencies, safe instance and readiness check. A short-lived CLI needs no server. |
| Doctor | Read-only identification of the target source/build, endpoint or executable, prerequisites and isolated instance before driving it. |
| Drive | Concrete user actions through the inspected entry point, inputs and expected observations fixed before execution. |
| Evidence | How to judge responses and required side effects, what to save and the run-specific location outside scratch state. |
| Cleanup | Remove only this run's owned processes/resources; preserve evidence, including after failure. No process-name kills or borrowed sessions. |

For each helper specify its interpreter, invocation, cwd, arguments, dependencies,
side effects and exit/result meaning. Do not leave placeholders in the proven
recipe. Native test results are useful evidence but cannot replace checking the
actual operation's output and state. Direct internal setters or verification-only
endpoints do not demonstrate a user path. Identify any substituted external
boundary and what remains untested. Never relax expectations to obtain a pass.

Create `features/README.md` as a small index and a linked file for the selected
feature. Each entry maps the user-visible behavior and entry point to prerequisites,
concrete operations, expected observations and side effects, their contract sources,
limitations and other not-run surfaces. Use the project's terminology and existing
record format; no particular headings or universal harness are required.

## Execute, judge and retain

Mark the candidate **draft** until its own complete recipe has passed. For every
attempt, save a new record using the project's existing format, or a small JSON
record if none exists. Include:

- run identity/time, target revision and dirty/unknown state (plus relevant file
  hashes when the executed inputs are uncommitted), build/runtime and agent used;
- feature and entry point, exact commands/cwd/inputs, expectations fixed before
  Drive, observed results and references to the matching artifacts;
- separate feature result and cleanup result, with the resources owned by this
  run and confirmation that the evidence still exists after cleanup.

Do not capture credentials, secrets, real user datasets or unnecessary personal
information. Do not reuse earlier artifacts as the current run's proof.

| Result | Meaning |
| --- | --- |
| pass | Executed this entry point and proved its declared observations and side effects. |
| fail | Executed, but an expected result did not hold. Exit zero alone is insufficient. |
| blocked | A prerequisite prevented execution; record what is missing. |
| not-run | Known scope deliberately not executed in this attempt. |

Draft/verified describes the skill version, not the individual run's result.
Blocked and not-run never count as pass. A failed or unconfirmed cleanup prevents
handoff as a completed proof, even if feature observations passed.

Run Launch, Doctor, Drive, Evidence and Cleanup from the candidate. Always perform
owned cleanup after a failed attempt before fixing and rerunning. Check the retained
artifacts after cleanup. Only then promote the candidate through existing placement.

Use a disposable fixture/copy to challenge the proof: normal behavior passes;
an operation that exits zero but has wrong output or side effects fails; a missing
prerequisite and an unexecuted feature cannot pass; failed attempts remove owned
scratch state while retaining evidence. Do not inject faults into production code.

Have a fresh session, without the generation conversation, read the candidate and
repeat its recipe. If another agent product is already available and authorized,
use the same canonical generator to generate/update in a disposable destination
and execute the result there. Verify reapplication preserves unrelated/hand-written
files. Do not install a new agent stack just for this check. Report unavailable
behavioral checks separately from standard-format and byte-placement checks.

Report canonical and generated paths, path-based invocation, reused mechanisms,
proven feature/entry point/environment/agent, evidence, failure detection and
cleanup/replay results. Explicitly list blocked/draft/not-run scope. Do not add
maintenance scheduling, broad feature mapping or a new installation mechanism.

For provenance and redistribution terms, see [sources](references/sources.md).
