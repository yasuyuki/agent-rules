# Composition

Select this profile with an explicit readable `agent-environment` Git checkout.
Doctor accepts only its
`examples/single-environment/rules/example-private.rule.md`, rejects linked
inputs, and records its revision, dirty state, and hash. The helper copies that
example into scratch; it never reads a live private catalog or changes an actual
environment checkout.

In addition to [placement](placement.md), it requires these independently
checked outcomes:

1. Repeated public `--rules` composition projects both the copied example and
   a synthetic workspace rule; after an update, both remain and the selected
   dependency hash is unchanged.
Live bindings, controller dispatch, Windows, package CLI, remote placement, and
native agent loading remain `not-run`. It does not authorize deployment.
