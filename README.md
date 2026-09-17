# Agent Rules

Manage your own rules and skills across Claude Code, Codex, Cursor Agent,
Antigravity, OpenCode and Grok. One editable source is copied into each tool's
file layout; checks detect drift while preserving unrelated instructions.
The project CLI does not install the maintainer's policies or require an agent
CLI, credentials, or private repository.

## Start from source

Use Python 3.10+ and Git on Windows or Linux. There is no confirmed PyPI release
of this project; the following installs this repository, not a same-named package.
In a terminal (`cmd.exe` on Windows), with `python` naming your Python 3.10+
interpreter (use `python3` on Linux if needed):

```console
git clone https://github.com/yasuyuki/agent-rules.git
cd agent-rules
python -m venv .venv
```

Activate the environment: `.venv\Scripts\activate.bat` on Windows, or
`source .venv/bin/activate` in Bash on Linux. Then install:

```console
python -m pip install .
agent-rules --version
```

In the same activated terminal, change to the project you want to manage and run:

```console
agent-rules init
```

Choose tools and your source folders at the prompts. The initializer creates
`.agent-rules/config.json` and empty sources; it never overwrites an existing
configuration. Add a rule or skill using the
[project guide](https://github.com/yasuyuki/agent-rules/blob/main/docs/manual.md#project-rules-and-skills),
then run:

```console
agent-rules apply
agent-rules check
```

A successful check reports matching managed output. Edit the sources and apply
again for updates; an empty source is explicitly reported, not installed policy.

## Guides

- [User manual](https://github.com/yasuyuki/agent-rules/blob/main/docs/manual.md):
  project configuration, source authoring, advanced placement and launch,
  environment catalogs, reports, branch management, and shared handoffs.
- [Optional necessity hooks](https://github.com/yasuyuki/agent-rules/blob/main/docs/necessity-hooks.md):
  explicitly enabled candidate review; normal installation does not call a model.
- [Development and CI](https://github.com/yasuyuki/agent-rules/blob/main/docs/ci.md):
  build, verification, coverage and retained evidence.
- [Verification skill acceptance](https://github.com/yasuyuki/agent-rules/blob/main/docs/verification-skill.md):
  demonstrated scope and historical evidence, not a substitute for a fresh run.

MIT. See [LICENSE](https://github.com/yasuyuki/agent-rules/blob/main/LICENSE).
