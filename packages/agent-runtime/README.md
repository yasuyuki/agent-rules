# Agent runtime

`agent-runtime` is an independently installable Python 3.10+ package that
connects the standard `codex`, `claude`, and `grok` names to explicitly
configured vendor executables. It does not import agent-rules, private
configuration, placement, inventory, or workspace state implementations.

Install it in an isolated environment:

```console
python -m pip install .
agent-runtime --help
```

Set `AGENT_RUNTIME_CONFIG` to an explicit version-1 JSON configuration, or
pass `--config PATH` to `agent-runtime` before the tool name. A configuration declares the
absolute vendor argv for each tool and each allowed workspace. Workspaces are
matched by canonical real path; the deepest match must be unique and active.
The runtime refuses unknown, pending, held, ambiguous, and tool-disabled
workspaces.

Each workspace supplies a fixed, SHA-256 pinned lifecycle CLI. The runtime
calls its public `resolve-run` interface and never reads lifecycle state or Git
metadata. A HANDOFF receiver, when required, is likewise a fixed, source-hash
bound CLI; its owner is explicitly `runtime` or an attested external GUI owner.
Native cwd options remain in the vendor argv while the selected cwd is checked
before launch. Tool-specific maintenance commands can read the configured tool
binding while skipping malformed workspace declarations; they never select an
ambient `PATH` vendor.

The small schema keeps host-specific values in the configuration owner. This
illustrates its shape; every shown path is a placeholder and every pin is the
SHA-256 of the invoked source file.

```json
{
  "version": 1,
  "tools": {"codex": {"argv": ["/absolute/vendor/codex"]}},
  "workspaces": [{
    "root": "/absolute/workspace",
    "state": "active",
    "tools": ["codex"],
    "lifecycle": {
      "argv": ["/absolute/bin/workspace-lifecycle"],
      "source": "/absolute/bin/workspace-lifecycle",
      "interface": "resolve-run-v1",
      "pins": [{"path": "/absolute/bin/workspace-lifecycle", "sha256": "..."}]
    }
  }]
}
```

The command help is the authoritative reference for launcher arguments. The
runtime does not generate configuration, scan environments, adopt workspaces,
look up versions or models, or finish lifecycle work. A lifecycle finish needs
the separately reviewed plan and result evidence required by its owner.

## Adoption and rollback boundary

Version 0.1.0 is source-only, not a confirmed PyPI publication. Build the wheel
from the accepted source revision and install it alongside the separately pinned
workspace-lifecycle 0.2.0 wheel in an isolated environment. Pins identify the invoked
entry and any adopted package files requiring drift detection; the environment
owner controls their installation and source revision. Normal launch never
repairs changed pins or grants trust.

For HANDOFF, use the existing fixed receiver CLI with `owner: "runtime"`, `argv`,
`source` and `source_sha256`; the runtime passes the selected workspace root.
A GUI-owned route uses `owner: "external", attested: true` only after its adoption
proves receipt before CLI launch. This is a route-level declaration, not a receipt
created by the runtime. Do not use that route outside its GUI precondition.
For independent work after receipt failure, explicitly launch through
`agent-runtime --handoff-independent`; the warning remains on stderr.

Switch a consumer only after checking its package/config/entry identity and
synthetic acceptance. Keep its previous entry, config, hooks and state together
until that separate live acceptance. Revert using that preserved set only after
preserving and reconciling work created after the switch; do not overwrite new
results. This source change does not switch Windows or Linux consumers.

The runtime enforces launch scope, not confinement after launch. Native changes
of directory or creation of other worktrees remain vendor behavior. Lifecycle
context exposes its fixed `finish_argv`; a reviewed plan and result reference
remain mandatory. Child exit alone does not finish a task. Neither this adapter
nor lifecycle intercepts arbitrary direct Git operations or guarantees cleanup
after an uncatchable forced termination.
