# Rulesync composition

The operator combines explicitly selected inputs and safely refreshes native
rules and skills. The inspected contract is agent-environment's
`examples/rulesync/README.md`, `placement.json`, and
`sources/rules/private-example.md`. Agent-rules' `docs/manual.md` and
`tests/test_rulesync_backend.py` define source selection and ownership behavior.

Use the [skill recipe](../SKILL.md). The helper copies the synthetic example,
uses its three declared targets, and adds a synthetic `environment-proof` skill.
Its public entry is the installed `agent-rules` executable with explicit config
and backend arguments. Every command runs in the owned copied project.

The observations are fixed before Drive.

| Operation | Required observation and side effect |
| --- | --- |
| Initial apply and check | `AGENTS.md` and `.claude/rules/private-example.md` contain the exact synthetic policy body. Codex/Grok share `AGENTS.md`; root `CLAUDE.md` is absent. The selected skill and its support file exist under `.agents`, `.claude`, and `.grok` skill roots. |
| Reapply | Output bytes and modes stay identical. The ownership manifest lists only the expected generated files. Handwritten skill and unrelated note remain outside its ownership. |
| Change copied input and apply/check | Both generated rule files show the new exact body. All other expected files and the handwritten content remain correct. The original checkout's input hashes stay unchanged. |
| Add a copied source with an unowned existing skill name | Apply exits nonzero and identifies the unowned handwritten skill as the refusal reason. Output bytes, modes, and ownership remain unchanged. The handwritten skill survives. |

Each attempt retains `result.json`, exact command logs, fixed expectations,
input hashes, and initial, updated, and rejected-output snapshots outside scratch.
Feature and cleanup results are separate. Cleanup removes the entire owned copy
and confirms that evidence still exists. A missing backend prevents execution;
Doctor-only executes no feature.

The synthetic skill and unrelated files substitute private and project inputs.
No real policy data enters this proof. Native agent discovery, instruction
obedience, global scope, legacy declarations, deployment, Windows, remote hosts,
and runtime/lifecycle state are not-run.
