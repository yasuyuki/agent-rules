# Agent Rules

Place explicitly selected rules and skills with **Rulesync 16.39.1**. Rulesync
owns format generation; a small staging adapter protects unowned files, rejects
conflicts, removes only owned stale output, and restores failed writes.
No agent CLI, credentials, private repository or maintainer policies are required.

## Start from source

Use Python 3.10+ and Node.js 22+ on Linux or Windows. From this checkout:

```console
npm ci --ignore-scripts
python -m pip install .
```

Create native Rulesync sources and an explicit placement configuration using the
[project guide](docs/manual.md#project-rules-and-skills), then run:

```console
agent-rules apply --config rulesync-placement.json
agent-rules check --config rulesync-placement.json
```

Select the installed Rulesync executable with
`--rulesync` when it is not on PATH. There is no implicit download or initial
sample policy. Check compares generated output without writing the destination.
The prepared Python package has not been published to PyPI.

## Sources and migration

Common policies in `rules/` remain one editable source; export explicitly chosen
inputs as described in the [manual](docs/manual.md#declared-placement-and-source-authoring).
Generic skills are edited in [agent-skills](https://github.com/yasuyuki/agent-skills).
Project-specific skills remain here. There is no reverse mirror command.

The checkout's declaration/runtime commands are a temporary compatibility surface
for consumers pinned before the source transition. They are not bundled with the
project CLI. Live adoption and removal are tracked by
[#15](https://github.com/yasuyuki/agent-rules/issues/15); installing this source
alone does not update a running environment.

- [User manual](docs/manual.md): source selection, ownership and migration boundaries.
- [Development and CI](docs/ci.md): build and verification.
- [Agent runtime guide](packages/agent-runtime/README.md): independent native CLI adapter and explicit adoption boundary.
- [Workspace lifecycle guide](https://github.com/yasuyuki/workspace-lifecycle): independent task, finish, integration and retirement contract.
- [Necessity review](https://github.com/yasuyuki/necessity-review): independent owner and management CLI; existing fixed consumers can retain their accepted agent-rules revision until separately migrated.

MIT. See [LICENSE](LICENSE).

Checkout lifecycle compatibility entries require the independently installed
[workspace-lifecycle 0.2.1](https://github.com/yasuyuki/workspace-lifecycle).
Its source, build and lifecycle tests belong to that repository; this repository
keeps only the existing compatibility entries and tests their public interface.
