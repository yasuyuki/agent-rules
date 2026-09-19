# Feature map

| Profile | Select when | Evidence produced |
| --- | --- | --- |
| [Placement](placement.md) | Testing projection and safe reapplication in one disposable project | Managed rule/skill update, hand-written preservation, and collision rejection |
| [Composition](dependencies.md) | Also testing one selected `agent-environment` example | Additional source composition with a selected dependency rule |

The dependency profile includes placement. It is opt-in: the default run leaves
composition `not-run`. These profiles exercise public file projection,
not `agent-rules init`, native agent discovery/loading, remote placement, or a
deployed environment.
