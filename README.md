# Agent Rules

Keep your rules and skills in selected source directories, then place them in the
native file locations for the agents you choose. Run `apply` after editing a
source and `check` to detect drift. **Rulesync 16.39.1** generates the files;
the staging adapter protects unowned files, rejects conflicts, removes only
owned stale output, and restores failed writes. The CLI runs only when called.
No agent CLI, credentials, private repository or maintainer policies are required.

## Start from source

Use Python 3.10+ and Node.js 22+ on Linux or Windows. From this checkout, use
a virtual environment so installation does not change your global Python.
On Linux:

```console
python3 -m venv .venv
.venv/bin/python -m pip install .
npm ci --ignore-scripts
```

On Windows PowerShell:

```console
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
npm.cmd ci --ignore-scripts
```

Create native Rulesync sources and an explicit placement configuration using the
[project guide](docs/manual.md#project-rules-and-skills). From the project that
contains `rulesync-placement.json`, run the installed CLI with the Rulesync
executable in this checkout. On Linux:

```console
/absolute/path/to/agent-rules/.venv/bin/agent-rules apply --config rulesync-placement.json --rulesync /absolute/path/to/agent-rules/node_modules/.bin/rulesync
/absolute/path/to/agent-rules/.venv/bin/agent-rules check --config rulesync-placement.json --rulesync /absolute/path/to/agent-rules/node_modules/.bin/rulesync
```

On Windows PowerShell:

```console
& "C:\path\to\agent-rules\.venv\Scripts\agent-rules.exe" apply --config rulesync-placement.json --rulesync "C:\path\to\agent-rules\node_modules\.bin\rulesync.cmd"
& "C:\path\to\agent-rules\.venv\Scripts\agent-rules.exe" check --config rulesync-placement.json --rulesync "C:\path\to\agent-rules\node_modules\.bin\rulesync.cmd"
```

You may omit `--rulesync` if the executable is on PATH or in `node_modules/.bin`
beside the configuration or current directory. `npm ci` in a different checkout
does not make its executable available to a project. There is no implicit
download or initial sample policy. Check compares generated output without
writing the destination. See the [removal steps](docs/manual.md#remove-managed-output).
The prepared Python package has not been published to PyPI.

## Sources and migration

The repositories in this section are optional for project `apply` and `check`.
Common policies in `rules/` remain one editable source; export explicitly chosen
inputs as described in the [manual](docs/manual.md#declared-placement-and-source-authoring).
Generic skills are edited in [agent-skills](https://github.com/yasuyuki/agent-skills).
Project-specific skills remain here. There is no reverse mirror command.

Runtime launch and the optional historical receiver are owned by
[agent-runtime](https://github.com/yasuyuki/agent-runtime), not this checkout.
Windows GUI consumers retained on their fixed historical agent-rules revision stay
outside this compatibility surface until their separate adoption.

- [User manual](docs/manual.md): source selection, ownership and migration boundaries.
- [Development and CI](docs/ci.md): build and verification.
- [Agent runtime](https://github.com/yasuyuki/agent-runtime): native CLI adapter and HANDOFF receiver owner.
- [Workspace lifecycle guide](https://github.com/yasuyuki/workspace-lifecycle): independent task, finish, integration and retirement contract.
- [Necessity review](https://github.com/yasuyuki/necessity-review): independent owner and management CLI; existing fixed consumers can retain their accepted agent-rules revision until separately migrated.

MIT. See [LICENSE](LICENSE).

Inventory inspection uses a read-only compatibility import from the independently
installed [workspace-lifecycle](https://github.com/yasuyuki/workspace-lifecycle).
Use its CLI directly for task, finish, integration and retirement operations.
Push preflight uses the fixed independent package directly. Its source, build and
lifecycle tests belong to that repository.

## Resuming work

Use the owning task for remaining work and acceptance, operations documentation for
procedures, and task evidence for retained results. Workspace-wide `HANDOFF.md`
creation and updates are retired. Preserve and reconcile existing contents before
removing each consumer; retire its receiver through the owning runtime configuration.
See [the vocabulary](CONTEXT.md) and [decision](docs/adr/0001-task-owned-resumption.md).
