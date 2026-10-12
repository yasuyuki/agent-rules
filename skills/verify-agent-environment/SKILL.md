---
name: verify-agent-environment
description: Verify agent-environment's Rulesync source composition through apply and check in a disposable project, with retained output, collision protection, and cleanup evidence.
license: MIT
---

# Verify agent-environment

Verified on Linux with Codex through the complete recipe and a fresh-session
replay. Each later run needs fresh evidence.

Read [the feature map](features/README.md) and
[the selected proof](features/rulesync-composition.md).
Use an explicitly selected agent-environment checkout. Its configuration is the
input under test. The public agent-rules CLI and Rulesync generate output.

## Launch and Doctor

Run on Linux with Python 3.10+, Git, Node.js 22+, an installed agent-rules CLI,
and the target's pinned Rulesync 16.39.1 executable. Use existing installations.
This recipe installs nothing and launches no agent or server.

From the selected agent-environment root, set `verification_skill` to the
directory containing this file. Set `placement_entry` and `rulesync_backend` to
the absolute executables documented by the selected environment's Rulesync
README. Set `evidence_root` to a persistent private directory outside the
checkout and temporary directories. Set `driving_agent` to the actual agent.

```sh
python3 "$verification_skill/scripts/verify.py" --environment-repo "$PWD" \
  --entry "$placement_entry" --rulesync "$rulesync_backend" \
  --evidence-root "$evidence_root" --agent "$driving_agent" --doctor-only
```

Doctor records the target revision, dirty state, input and helper hashes,
executable identities, runtime versions, and exact commands. It validates the
synthetic example's relative source/output boundaries before Drive. Doctor-only
is `not-run`, never a feature pass. Missing prerequisites are `blocked`.

## Drive and evidence

Use the same arguments without `--doctor-only`.

```sh
python3 "$verification_skill/scripts/verify.py" --environment-repo "$PWD" \
  --entry "$placement_entry" --rulesync "$rulesync_backend" \
  --evidence-root "$evidence_root" --agent "$driving_agent"
```

The helper's `--help` defines its arguments. It uses Python's standard library
and the real CLI subprocess interface. It copies only `examples/rulesync`'s
placement config and synthetic rule into new scratch state. It adds a synthetic
skill source and unrelated handwritten files there. Live declarations, HOME,
credentials, hooks, runtime and source files are outside its write scope.

The helper fixes expectations before the first apply. It exercises initial
apply/check, reapply, source update, and an unowned same-name skill collision.
It checks exact generated rule and support-file bytes, skill content, ownership,
unchanged reapplication, preserved handwritten files, and unchanged output on
rejection. A zero exit alone cannot pass.

Read the printed `result.json`, its assertions, command logs, and saved output
snapshots. `feature_result` describes this one entry point. `result` also
requires successful cleanup and retained evidence. Exit codes are 0 for `pass`,
1 for `fail`, 2 for `blocked`, and 3 for `not-run`.

## Cleanup and report

The helper waits for each owned subprocess and removes only its new scratch
directory in a `finally` block, including after failure. It confirms scratch
absence and retained artifacts before saving the final record. After an
interruption, use the record's exact scratch path and inspect its ownership
before recovery. Preserve the evidence directory.

Report the target revision, actual agent, feature and cleanup results, and
evidence path. Native discovery, model behavior, live maintenance, other
environments, runtime launch, necessity review, and push decisions remain
`not-run`. Synthetic success does not certify deployment.

When changing this proof, run its detector challenges from this skill directory.

```sh
python3 scripts/test_verify.py
```
