# Placement

The default helper profile drives `bin/place.py apply` and `check` against a
new local project and synthetic declaration, rule, and skill inputs. It requires
Python 3.10+, Git, and a readable checkout with `bin/place.py`, `placement.json`,
`rules/`, and `skills/`; it needs no agent installation or authentication.

Before each operation, the helper declares and later records these independent
expectations:

1. The first apply creates one blue managed probe section, copies the probe skill
   and its reference bytes, and preserves seeded local instructions, an unrelated
   file, and an unmarked hand-written skill.
2. A check succeeds. The source rule is then changed to green; reapply/check
   leaves one green section, removes blue, and preserves the other content.
3. A source skill colliding with the unmarked hand-written skill is rejected and
   leaves the project byte-identical. This expected rejection proves safe update;
   it is not a failed verification.

The helper snapshots output and compares it itself, so public CLI success does
not substitute for persisted-content checks. Its fixture uses supported inputs
and public commands, never internal state setters. Scratch is owned by the run;
evidence survives cleanup.

This chooses the Codex file layout only to bound the fixture. It does not prove
native Codex loading, package CLI, other layouts or operating systems, remote
launch, or installed-agent behavior. Do not treat the collision refusal as a
product defect or run against real private catalogs.
