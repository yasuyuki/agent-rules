# Other environment entry points

These entries identify known behavior without declaring it tested. Resolve all
paths from the explicitly selected agent-environment checkout and its owner's
configuration. Execution requires that entry's existing authorization and host.
This skill neither switches environments nor performs live adoption.

| Behavior and contract source | Operation and prerequisites | Expected observation and effects | Limitation |
| --- | --- | --- | --- |
| Rule/skill maintenance. `rulesync/ubuntu-26-development/README.md`, `rulesync/windows-controller/README.md`, `rulesync/ubuntu-operator/README.md`, `rulesync/isolated-code/README.md` | Select the named config and fixed adapter/backend. Use its documented apply/check/reapply path. Isolated-code uses trusted setup. | Only declared owned outputs change. Check passes, reapply is unchanged, native discovery finds selected inputs once. | No live config or host exercised. Handover and GUI acceptance require their own contracts. |
| Cross-environment reflection. `pstack/README.md`, `pstack/environments.json`, `tests/check_sources.py` `EXPORTS` | After integration, run `pstack/sync.py place` on the Windows controller with Python 3.14. It needs each environment's transport, adapter and backend, and network access for export builds. | Every source checkout is fast-forwarded. A missing selected export is built from `EXPORTS`, on the operator by copying from ubuntu-26-development with matching digests. Changes outside the pstack skill roots apply only when every input of that config is sourced. Each config passes check and reapply is unchanged, and `ok` is true for all three environments. | Writes live outputs on three hosts; this skill does not drive it. Product acceptance stays with agent-environment #18. |
| Native launch. `runtimes/README.md`, `runtimes/windows-controller.md`, `runtimes/ubuntu-24-experiment.md` | Resolve the selected workspace binding. Invoke the documented standard entry with an authorized vendor on that host. | Correct workspace/vendor and permissions apply. Startup does not generate or check placement. Current task state is retained. | No launch, model execution, device, Windows GUI, or sealed experiment tested. |
| Native workflow and settings. `pstack/README.md` | Use the chosen host's deployed workflow in a new authorized native session. Read only that product's settings reference. | Native task tools actually execute. The profile matches session identity and handwritten/vendor assets survive placement. | Byte placement does not prove delegation, model identity, or cross-product behavior. |
| Push decision. `rules/push-policy.json`, `rules/git-push-policy-location.rule.md` | Use the environment's fixed independent push preflight and explicit policy against the intended repo. | Decision and reason match the user's scope and destination. The decision operation does not push. | No private policy contents read or push performed by this proof. |
| Bounded necessity review. `necessity/ubuntu-26-development/README.md`, `necessity/windows-development/README.md` | Use the independent necessity-review owner with the documented settings and eligible workload. | Only the declared scope is reviewed. Existing exclusions, permissions, and private state persist. | No hooks or evaluation state exercised. |

Other historical declaration, dispatch, and adoption routes need their own
owner acceptance. This map is an index, not permission to execute them.
