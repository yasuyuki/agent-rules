---
name: verify-agent-rules
description: Verify agent-rules CLI placement and safe updates, optionally including agent-environment source composition and agent-skills mirror output, with disposable data and retained evidence.
license: MIT
---

# Verify agent-rules

Procedure status: **verified** on Linux for placement, dependency composition
and mirror, including a fresh Codex session replay. This is not a future run's result.
The demonstrated environment is Linux with Python 3.10+ and Git; no installed
agent CLI or private configuration is required.

Read [the Feature Map](features/README.md) and [placement recipe](features/placement.md).
For dependent repositories, also read [composition and mirror](features/dependencies.md).
Use this skill to execute verification. Regeneration requires an explicit request.
All relative helper paths below start at this skill directory; repository paths
are relative to the separately selected agent-rules checkout.

## Launch

This is a short-lived CLI; there is no server to start. From the selected
agent-rules repository root, the source copy of this skill is invoked with:

```sh
python3 skills/verify-agent-rules/scripts/verify.py --repo .
```

For the dependency profile, select the `agent-environment` Git checkout explicitly
and set `AGENT_ENVIRONMENT_REPO` to its absolute path in a separate shell command.
Do not combine that assignment with the invocation below. From
the agent-rules checkout root, run:

```sh
python3 skills/verify-agent-rules/scripts/verify.py \
  --repo . --environment-repo "$AGENT_ENVIRONMENT_REPO" --agent "Codex"
```

Replace the agent label with the actual driving product/model. The dependency
argument selects only the repository's synthetic example rule, never its live
rules or declaration. The mirror destination is always a newly owned scratch
directory; an installed `agent-skills` checkout is not required or modified.
The same options may be passed to a distributed helper by its actual path.

If reading a distributed skill, run its `scripts/verify.py` by its actual path
and pass the selected checkout via `--repo`. Do not guess a checkout from HOME.
The helper uses only Python's standard library and Git. It runs the existing
`bin/place.py` CLI as subprocesses, without imports of application internals.
It creates new synthetic inputs, a private temporary project and a separate
evidence directory. It does not launch agents, install dependencies, read private
placement settings, use network services or write real user data.

## Doctor

For read-only source identification before Drive, from the same cwd:

```sh
python3 skills/verify-agent-rules/scripts/verify.py --repo . --doctor-only
```

Doctor checks Python, Git revision/dirty state, and the public entry point and
input directories. It hashes executable source and public inputs for this run.
Add `--environment-repo` and `--agent` to Doctor when using the dependency profile;
it also identifies and hashes that selected synthetic input before any Drive.
It writes only a new evidence record, leaving the target source unchanged.
An unmet prerequisite yields `blocked`; a successful Doctor leaves the feature
`not-run`. Neither proves placement. Full verification repeats Doctor before
creating its isolated instance; its recorded fixture paths identify that instance.

## Drive

Run the Launch command. The helper executes the literal CLI actions and checks
in [placement](features/placement.md): initial apply/check, source update and
reapply/check, then a collision with a hand-written skill. It reads the generated
bytes after each relevant operation and records the expected and actual values.
Its generated configuration and source files are normal public inputs. No internal
state setters, private configuration or external-system substitutes are used.
The dependency profile additionally composes a second rule source through repeated
`--rules`, then mirrors original skills, detects output drift and repairs it.
Only scratch copies are changed. Expectations are fixed before these operations.

## Evidence

Each invocation prints the result and absolute path to a new `result.json`.
By default its directory is created under the OS temporary directory with prefix
`agent-rules-evidence-`. `--evidence-root` optionally selects an existing or new
parent; every run still gets a fresh child. Keep the printed location.

The record contains revision, dirty state, public input and helper hashes, Python,
platform, invoked entry point, commands/cwd/exit/stdout/stderr, prior expectations,
observed bytes, filesystem artifact references, and cleanup outcome. Logs contain
only synthetic inputs and public source; do not use this helper on secret-bearing
rule/skill catalogs. `--agent` records the driving product/model (`unknown` if
omitted); include its known version in that label or the session report.

`pass` requires all declared behavior and successful cleanup. `fail` means an
observed mismatch or execution/cleanup failure; `blocked` means Doctor or safe
fixture preparation could not complete; `not-run` means Doctor-only was requested.
Exit codes are respectively 0, 1, 2 and 3. A CLI exit zero without expected file
contents cannot pass. Read the assertions and artifacts, not just the final label.
Read each selected feature's status: a default placement run leaves composition
and mirror **not-run**, and a failure in a later feature does not erase an earlier
feature's observations. A dependency-profile pass requires all selected features.

## Cleanup

The helper waits for each short-lived child and removes only its own newly created
scratch directory in `finally`, including after failure or interruption. Evidence
is outside scratch, saved before deletion and checked afterward. `cleanup.ok` and
the retained artifact list must both be confirmed before reporting completion.
Never delete a path inferred from another run's record or kill by process name.
If cleanup fails, report its exact owned path and error; the run cannot pass.

Failure-detector regression, from this repository root:

```sh
python3 tests/test_verification_skill.py
```

This is a test of the proof mechanism, not additional feature coverage. Known
unexecuted surfaces are listed in the Feature Map. A fresh session must run the
same Launch recipe to produce its own evidence, not inherit a previous pass.
