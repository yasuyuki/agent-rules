# Sources consulted

Retrieved 2026-09-11 before implementation.

- [Cursor pstack generator](https://github.com/cursor/plugins/blob/f5bdd6826fd0a0d9cbc4347134c3a74a200b9d9d/pstack/skills/create-verification-skill/SKILL.md),
  repository commit `f5bdd6826fd0a0d9cbc4347134c3a74a200b9d9d`, skill blob
  `f869e26122991252373d5b8f6357e5b9ff195a00`.
- [Feature Map examples](https://github.com/cursor/plugins/tree/f5bdd6826fd0a0d9cbc4347134c3a74a200b9d9d/pstack/skills/create-verification-skill/references/feature-map-example):
  read README, create-note and search. The examples were inspected, not bundled.
- [pstack license](https://github.com/cursor/plugins/blob/f5bdd6826fd0a0d9cbc4347134c3a74a200b9d9d/pstack/LICENSE):
  MIT, Copyright (c) 2026 Lauren Tan. The complete notice is retained in
  `LICENSE.txt` at the skill root. This is an adapted workflow, not an upstream
  byte mirror. It removes Cursor/pstack invocation dependencies, narrows the map
  to a demonstrated feature and adds explicit results, ownership and proof gates.
- [Agent Skills specification](https://agentskills.io/specification), source
  [docs/specification.mdx](https://github.com/agentskills/agentskills/blob/69ef37e9424c0a7ea9dd2293b559e43ec8176379/docs/specification.mdx)
  at `69ef37e9424c0a7ea9dd2293b559e43ec8176379` (blob
  `d9a2db099d905da8b879a5c6f996728073985279`). Used standard frontmatter and
  relative resources; no vendor extension is required.
- [agent-rules](https://github.com/yasuyuki/agent-rules): remote main
  `30f523c22c339358b0367dde69216b345ef95360`; inspected local adopted checkout
  `184ec0fe7074cf4999337352c9cbfeb1f117342a`. Reused source/placement ownership,
  project CLI, and existing test entry points. The implementation topic starts
  at remote main; no private configuration is required by either skill.
