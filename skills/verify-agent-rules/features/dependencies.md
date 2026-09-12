# Dependent source composition and mirror

The repository roles follow the agent-rules README, “Existing declaration-based
usage” and “Skills”, agent-environment's README, “Use from work-records” and
“Live private inputs”, and agent-skills' README. agent-rules has no third-party
runtime package dependency. agent-environment supplies additional configuration;
work-records supplies workspace bindings and declarations; agent-skills receives
generated original skills. These are separate Git roots, not submodules.

## Inputs and isolation

Use the dependency Launch command in `../SKILL.md`, selecting a readable Git
checkout of agent-environment. Doctor reads only its
`examples/single-environment/rules/example-private.rule.md`, records its revision,
dirty state and input hash, and refuses links in that input path. Do not replace
the example with a live private catalog. Python 3.10+ and Git are the only runtime
prerequisites; no model, network, installed package or credentials are needed.

The helper copies the example into its owned scratch input directory. It uses
the existing synthetic Codex declaration from the placement recipe and a separate
synthetic workspace rule source. It does not execute or relocate an arbitrary
private declaration. work-records' extra-source role is represented by this
synthetic source; actual controller/dispatch behavior remains not-run.

The mirror destination is a new directory representing agent-skills' output
contract. No actual mirror checkout, its history or registration is changed by
the recipe. The existing public source and `skills/UPSTREAM.tsv` determine which
skills are eligible. Record this distinction from checking a deployed mirror.

## Operations and expectations

1. Apply with two explicit additional `--rules` sources. Require the public
   catalog's managed instructions, one `example-private` managed section matching
   the copied example's title/body, and the workspace probe. Check exits zero.
2. Reapply the updated workspace probe. Require the example and public instructions
   to remain and all placement-recipe preservation checks to pass. The source
   checkout's selected input hash must remain unchanged.
3. Seed `notes.txt` at the disposable mirror root. Run the real
   `bin/place.py mirror --skills SOURCE/skills --dest DEST`, then the same command
   with `--check`. Independently compare every mirrored skill's bytes (and POSIX
   execute bits) to the non-vendored source set; vendored skills must be absent.
   Require the root notes to remain identical.
4. Corrupt only the disposable mirrored verifier's `SKILL.md`. `mirror --check`
   must return nonzero and leave that output tree unchanged. Run `mirror` again,
   then `mirror --check`, and independently require the complete correct tree
   and preserved root notes. A zero exit without correct files fails the proof.

The record saves complete argv/cwd, input hashes, expectations, exit codes,
stdout/stderr, comparisons and filesystem snapshots outside scratch. CLI flags
above describe the public surface; the helper supplies and records concrete paths.
Use the printed `result.json`, not the illustrative flag names, to reproduce a run.

The mirror owns its entire `skills/` subtree and intentionally removes foreign
files there. Preservation assertions apply to mirror-root notes and to hand-written
project content under the placement contract, not additions inside mirror/skills.
This follows `bin/place.py`'s `mirror` implementation and its selfcheck, as well as
the README's authorship-filtering contract.

## Judgment, cleanup and limits

All selected features and owned cleanup must pass. Missing dependency input is
blocked before Drive; Doctor-only and omitted profiles are not-run. Follow
`../SKILL.md` for the result/exit meanings and cleanup: every attempt removes only
its own scratch directory, and retained artifacts are checked afterward.

Native test fixtures challenge exit-zero corruption, unavailable prerequisites,
unexecuted features and preservation of evidence after failed attempts. Those
tests verify the detector; the real CLI run and fresh-session replay prove the
declared operation. The fresh session must receive the skill path, both checkout
paths and its own evidence parent, without the generation conversation.

Live private bindings, the example's Claude layout, dispatch launch, installed
agent-skills history, remote placement, Windows, package CLI, and native model
loading/obedience are not-run. A successful synthetic composition/mirror does
not establish those behaviors. An ordinary verification request does not
authorize replacing this skill or deploying the tested output.
