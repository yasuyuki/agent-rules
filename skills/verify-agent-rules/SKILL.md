---
name: verify-agent-rules
description: Verify agent-rules declaration-based CLI placement, updates and preservation of hand-written files in a disposable project, retaining action and filesystem evidence.
license: MIT
---

# Verify agent-rules

Procedure status: **verified** on Linux through the declared placement path,
including an independent session replay. This is not the result of a future run.
The demonstrated environment is Linux with Python 3.10+ and Git; no installed
agent CLI or private configuration is required.

Read [the Feature Map](features/README.md) and [placement recipe](features/placement.md).
Use this skill to execute verification. Regeneration requires an explicit request.
All relative helper paths below start at this skill directory; repository paths
are relative to the separately selected agent-rules checkout.

## Launch

This is a short-lived CLI; there is no server to start. From the selected
agent-rules repository root, the source copy of this skill is invoked with:

```sh
python3 skills/verify-agent-rules/scripts/verify.py --repo .
```

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

## Evidence

Each invocation prints the result and absolute path to a new `result.json`.
By default its directory is created under the OS temporary directory with prefix
`agent-rules-evidence-`. `--evidence-root` optionally selects an existing or new
parent; every run still gets a fresh child. Keep the printed location.

The record contains revision, dirty state, public input and helper hashes, Python,
platform, invoked entry point, commands/cwd/exit/stdout/stderr, prior expectations,
observed bytes, filesystem artifact references, and cleanup outcome. Logs contain
only synthetic inputs and public source; do not use this helper on secret-bearing
rule/skill catalogs. Record the driving agent/product in the session report.

`pass` requires all declared behavior and successful cleanup. `fail` means an
observed mismatch or execution/cleanup failure; `blocked` means Doctor or safe
fixture preparation could not complete; `not-run` means Doctor-only was requested.
Exit codes are respectively 0, 1, 2 and 3. A CLI exit zero without expected file
contents cannot pass. Read the assertions and artifacts, not just the final label.

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
