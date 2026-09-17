# Composition and mirror

Select this profile with an explicit readable `agent-environment` Git checkout.
Doctor accepts only its
`examples/single-environment/rules/example-private.rule.md`, rejects linked
inputs, and records its revision, dirty state, and hash. The helper copies that
example into scratch; it never reads a live private catalog or changes an actual
environment or mirror checkout.

In addition to [placement](placement.md), it requires these independently
checked outcomes:

1. Repeated public `--rules` composition projects both the copied example and
   a synthetic workspace rule; after an update, both remain and the selected
   dependency hash is unchanged.
2. Public `mirror` writes only to a new disposable destination. The helper
   compares every eligible non-vendored skill byte and POSIX execute bit, while
   preserving a seeded mirror-root note.
3. After corrupting only the disposable verifier output, `mirror --check` must
   reject it without mutation. A new mirror operation repairs it, and a final
   check plus independent comparison succeeds.

The mirror owns its generated `skills/` subtree; preservation applies to the
mirror root and placement project's hand-written content, not foreign files in
that generated subtree. A pass proves the selected synthetic composition and
mirror contract only. Live bindings, controller dispatch, mirror history,
Windows, package CLI, remote placement, and native agent loading remain
`not-run`. It does not authorize deployment or regeneration of the skill.
