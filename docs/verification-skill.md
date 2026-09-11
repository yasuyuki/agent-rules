# Verification skill MVP

The deliverables are the common
[`create-verification-skill`](../skills/create-verification-skill/SKILL.md) and
one generated, exercised [`verify-agent-rules`](../skills/verify-agent-rules/SKILL.md).
Their canonical source is this repository's `skills/` directory. Read a SKILL.md
by path and name the target checkout; no slash command or vendor API is required.
The project-specific proof replaces manually inspecting placed files after an
apply/update with reproducible operations, explicit comparisons and retained proof.

## Scope and existing mechanisms

The initial survey found canonical skills, `UPSTREAM.tsv`, byte/ownership-aware
`place.py apply/check/mirror`, standard Python test entry points, and the public
declaration-based CLI. No equivalent verification generator existed in the
inspected skill catalog. The existing normal Linux development environment had
Python, Git, Codex and Claude; no new agent installation or remote host was needed.

The selected real project is agent-rules itself. Its public placement CLI can
perform substantive file creation/update using an isolated synthetic declaration
and input sources without touching live placement, credentials or user data.
This was sufficient to prove one real user path; unrelated product repositories,
sealed releases and experiment baselines were not needed.

The generator is procedural Markdown. New executable code is limited to the
project verifier's standard-library helper and its regression tests. The helper
does not replace the public CLI or call its internal setters: it prepares normal
source/configuration inputs, invokes apply/check, reads files and keeps evidence
outside its owned scratch directory. agent-rules is the application under test,
not a private deployment/runtime framework required by the generator.

The source and driving agent are separate from the output file convention. This
MVP chooses the Codex file convention as one placement target; the driver only
needs Python and Git. It makes no claim about native agent discovery from those
generated files. Existing live placement is updated through `place.py`, never by
editing distributed skill copies. The upstream manifest keeps the adapted
generator out of the original-work-only public mirror; both skills are available
from this canonical repository and through normal declared placement.

## Acceptance and repeatable checks

Executor: an agent able to read a public Git checkout and run Python/Git. Cwd:
that checkout root. Inputs: its public code/catalog plus newly generated synthetic
declaration, rule and skills. Side effects: owned temporary project/evidence only;
no network, service, agent process or private configuration is required.

```console
python3 skills/verify-agent-rules/scripts/verify.py --repo .
python3 tests/test_verification_skill.py
python3 tests/test_rules.py
```

The first command prints its unique evidence location. An optional
`--evidence-root` changes the parent, never reuses a run. The second command is
also part of CI. It confirms that a real operation returning zero but persisting
wrong contents fails, missing prerequisites are blocked, Doctor-only is not-run,
and evidence survives owned cleanup. A linked public catalog is rejected before
reading outside the selected source. Windows may skip that link fixture when its
runtime cannot create links; the Linux test executed it.

The public placement selfcheck and source-format tests are reused. Skill Creator's
`quick_validate.py` accepted both skills; standard name/description/license fields
and relative references were also checked against the pinned Agent Skills
specification. Format checks do not substitute for agent execution.

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
