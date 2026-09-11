# Placement and safe update

A user supplies a public placement declaration and rule/skill sources, applies
them to a project, then reapplies changed sources without losing hand-written
instructions or skills. `check` reports whether managed output matches source.

## Entry and prerequisites

Use the checkout's documented `python3 bin/place.py` entry, with `apply` or `check`,
`--declaration`, `--rules`, and `--skills`. The helper in `SKILL.md` supplies actual
paths under the new run's scratch directory and records every complete argv.
Python 3.10+, Git and a readable checkout containing `bin/place.py`, `placement.json`,
`rules/` and `skills/` are required. No agent installation or authentication is used.

## Operations and expected state

The helper creates a normal Markdown TSV declaration with one local site, a
disposable workspace, and required rule/skill destinations for the Codex convention.
Its `verification-probe` rule initially says `Use the blue verification value.`;
its `verification-probe-skill` input has a Markdown body and a relative reference.
The source catalog's existing rule/skill inputs are included by the public CLI.

1. Seed hand-written `AGENTS.md` text, `notes.txt`, an unmarked `hand-written`
   skill and an unrelated file inside that skill. Apply the synthetic inputs.
   Require exit zero, exactly one managed probe section with the blue body,
   retained hand-written text, identical copied skill and reference bytes, and
   an ownership marker. All seeded unrelated files must remain byte-identical.
2. Check the same declaration and require exit zero. This is supporting evidence;
   the direct filesystem checks above are independently required.
3. Change the *source* probe body to `Use the green verification value.` and
   reapply/check. Require the green body, absence of the old blue body, one probe
   section, unchanged hand-written text and files, and unchanged skill contents.
4. Add a source skill named `hand-written`, colliding with the unmarked directory.
   Apply must return nonzero and leave the entire output project byte-identical
   to its pre-collision snapshot. This demonstrates reapplication does not replace
   a hand-written skill or unrelated files. It is an expected rejection, not a
   failed verification run.

The expectations are declared before CLI execution in the helper. Input creation
and step 3 edit source, never internal rendered state. Evidence includes initial,
updated and collision snapshots, command results and explicit comparisons. The
fixture is synthetic, but the application, public commands and file writes are real.

## Contract sources and limits

Read the target repository README, “Existing declaration-based usage” and “Skills”,
and `tests/test_rules.py` / `bin/place.py` selfcheck for the ownership marker,
source copying, managed-section preservation and unmarked-directory rejection
contract. The fixture uses the same supported declaration format; it does not
call selfcheck as a substitute for user operations.

Only the Codex **file layout** is selected to keep the MVP bounded. This does not
make Codex an execution dependency, and does not prove native Codex skill loading.
Package CLI, other layouts/OSes, remote launch and installed agents are not-run.
Do not interpret the expected collision refusal as an application defect. Do not
run against real user input catalogs containing secrets. Evidence survives cleanup.
