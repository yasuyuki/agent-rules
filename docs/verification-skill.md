# Verification skill acceptance

Use [verify-agent-rules](../skills/verify-agent-rules/SKILL.md) for a new
placement/composition/mirror run and its result interpretation. Use
[create-verification-skill](../skills/create-verification-skill/SKILL.md) only
when creating or revising a verifier. The canonical sources are this checkout's
skills; distributed copies need no vendor API or private environment binding.

This page preserves historical acceptance, including limits and failed attempts.
It does not make an old pass evidence for a new revision or host. The current
helper's CLI/help and regression tests own the executable procedure; the skill
keeps independent expected behavior and the boundary of each proof.

## Placement demonstration

Observed on 2026-09-11, Linux / Python 3.14.4 / Codex:

| Check | Observation |
| --- | --- |
| End-to-end placement | Initial apply/check, updated apply/check and expected collision rejection; 25 content/side-effect assertions passed. |
| Independent session | A fresh Codex session received only the generated skill location, target checkout and evidence parent; it executed the recipe and independently read retained output. |
| Failure detection | Five regression tests passed, including exit-zero corruption, blocked prerequisites, not-run and external linked catalog rejection. |
| Cleanup | Initial failed fixture attempt and successful/replayed attempts removed their owned scratch paths and kept evidence. |
| Reapplication | A hand-written skill and unrelated file survived update and a colliding input; output tree stayed byte-identical on rejection. |

Local evidence run ids include `agent-rules-evidence-pcs5fw2u` (initial fixture
failure: missing required EXCEPTIONS table, subsequently corrected),
`agent-rules-evidence-nowjzwkp` (first pass),
`agent-rules-evidence-sawlgjzk` (fresh session), and
`agent-rules-evidence-uyxizbuv` (review correction pass). Each record includes the
actual target revision/dirty state and public-input/helper hashes; earlier runs
do not stand in for current evidence. Runtime records and filesystem snapshots
remain outside Git. The operator's completion report links their retained location.

## Dependency profile (2026-09-11)

The optional dependency profile was added and exercised on 2026-09-11 using
Linux, Python 3.14.4 and Codex. Read the verifier's
[dependency recipe](../skills/verify-agent-rules/features/dependencies.md) for the
repository roles and exact input boundary. It reuses the existing helper and
public CLI; no installer or private runtime dependency was added.

The profile selects agent-environment's synthetic example rule by an explicit
checkout argument, supplies it alongside a second source via repeated `--rules`,
and proves both initial and updated output while preserving the original input.
The mirror proof uses a disposable agent-skills destination, independently checks
non-vendored bytes/execute bits, rejects deliberately corrupted output and repairs
it. The mirror owns its `skills/` subtree; root notes are preserved. work-records'
additional-source role is synthetic here, and its dispatch/live bindings are not-run.

The lead run and a fresh Codex session each passed 71 assertions across 15 real
CLI operations. The fresh session also exercised Doctor; an initial incorrect
shell variable assignment was blocked before Drive, then corrected without source
or permission changes. All attempts retained their own records. An independent
exit-zero/wrong-mirror-output challenge failed as expected and retained the wrong
bytes after removing scratch. Missing dependency input was blocked; Doctor-only
was not-run. The ten detector regressions and existing `tests/test_rules.py`
passed. Per-feature states, agent identity, input hashes, source-preservation
checks and initial/corrupt/repaired mirror snapshots are retained in `result.json`.

This extends functional coverage of configuration composition and mirror output,
not live dependent-repository deployment or native agent loading. A source-topic
or generated mirror-topic being verified does not mean it has been integrated;
deployment state belongs in the controller handoff and completion report.

## Limits

Claude Code 2.1.268 was also started through the environment's existing public
entry point. The initial attempt could not read paths outside its allowed
workspace. After source integration, a new session read the same canonical
generator and verifier, applied the generator twice to an isolated existing
candidate, and chose reuse because the owned files were already sufficient.
The hand-written addition and original source stayed byte-identical. Execution
and writing a result were rejected by its existing tool permissions, before
Doctor could start. Thus generator reading/reapplication is observed, but a
Claude functional run is **blocked**, with the feature **not-run**. Permissions
were not relaxed. This is separate from Codex's successful fresh-session replay
and the format checks; placement alone was never counted as execution.

Package CLI, other placement file conventions, other OSes, UI/API applications,
remote systems, full feature inventory, maintenance scheduling and native skill
discovery are not established by this MVP. The common generator is portable
instruction content; this single demonstration does not prove all agents or
execution environments. No installer, adapter suite, MCP server, generation
service, evidence service or persistent multi-agent arrangement was added.

Pinned references and pstack's retained MIT terms are documented in
[generator sources](../skills/create-verification-skill/references/sources.md).
