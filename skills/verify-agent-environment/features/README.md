# Agent-environment feature map

This map separates a reproducible synthetic proof from environment acceptance.
The [verification skill](../SKILL.md) runs only the selected composition proof.
Run records carry current results. A mapped entry alone has no pass status.

| User behavior | Entry point and prerequisite | Proof scope |
| --- | --- | --- |
| Compose private rule and selected skill sources without overwriting handwriting | Explicit `agent-rules apply/check --config … --rulesync …`, copied `examples/rulesync` | [Rulesync composition](rulesync-composition.md) |
| Maintain installed user and project rules and skills | Named `rulesync/<environment>` config and its owner README, reviewed fixed sources | [Other environment entry points](environment-entry-points.md), not-run |
| Start an agent with the selected runtime and lifecycle binding | Standard-name entry described by `runtimes/README.md`, actual host and authorized vendor | [Other environment entry points](environment-entry-points.md), not-run |
| Select the native pstack workflow and role settings | Native agent invocation with the selected `pstack/<environment>` inputs | [Other environment entry points](environment-entry-points.md), not-run |
| Apply private push policy or bounded necessity review | Independent owning package and explicit private settings | [Other environment entry points](environment-entry-points.md), not-run |

The terminology is owned by agent-environment's `CONTEXT.md`. Project-specific
verification source is owned here in agent-rules. Generated native copies are
placement output.
