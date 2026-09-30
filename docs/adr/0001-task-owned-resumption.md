# Keep resumption information with the owning task

A mutable workspace-wide HANDOFF accumulated unrelated dirty edits and stale copies of shared task state. Resumption information now stays in its owning task, operational documentation or task-specific private evidence; machine state is read from its existing owner. This removes the shared-file commit conflict while retaining a discoverable record of decisions and constraints that cannot be reconstructed.

The existing `handoff` rule identifier remains stable for deployed consumers. Existing documents and optional runtime receivers require a migration: preserve unique information, verify its destination, retire receiving bindings through their owner, then remove the old file. Local preservation alone does not establish cross-environment delivery.
