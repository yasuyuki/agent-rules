# Agent Rules

Manage your own rules and skills in a project, and project them into the file
layouts for Claude Code, Codex, Cursor Agent, Antigravity, and OpenCode.

The project CLI does not adopt the maintainer's policies. It needs no private
repository, distributed execution service, Git credentials, or installed agent
CLI. Existing unmanaged files and instruction text are preserved. Skill support
depends on the tool's placement conventions; unsupported kinds are reported.

## Requirements

- Python 3.10 or newer
- Windows or Linux; [pipx](https://pipx.pypa.io/stable/installation/) for isolated
  CLI installation. The application itself has no third-party runtime dependencies.

## Install and initialize a project

**Publication status:** this is a prepared package, not a confirmed PyPI release.
Do not install an unrelated package with the same name. Until publication and
name ownership are confirmed, install the locally built wheel from this source:

```console
pipx install ./dist/agent_rules-0.1.0-py3-none-any.whl
agent-rules --version
```

See [package development and publication](#package-development-and-publication)
to produce that wheel. After a verified PyPI publication, the installation
source can be replaced by the confirmed package name. Installation does not
modify any project's rules or skills.

Open a terminal in the project you want to manage and run:

```console
agent-rules init
```

Select tool ids when prompted (`claude`, `codex`, `cursor-agent`, `agy`,
`opencode`; comma or space separated). There is no preselected tool. Accept
the default source folders, or enter existing source directories of your own.
Enter `-` to leave a kind unmanaged. No agent CLI is launched or authenticated.

The initializer creates `.agent-rules/config.json` and, when selected, empty
`.agent-rules/rules/` and `.agent-rules/skills/` folders. It does not install
sample policies or change tool configuration. An existing config is never
overwritten; cancellation before completion leaves no partial configuration.

Add your first rule as `.agent-rules/rules/project-style.rule.md`:

```markdown
---
id: project-style
title: Project style
summary: Follow this project's documented conventions
---
Follow the conventions in this project's README.
```

A skill goes in `.agent-rules/skills/<name>/SKILL.md`, with `name` and
`description` frontmatter; `name` must match its directory. Supporting files
are copied alongside it. See [source format](#source-format) and [skills](#skills).

Apply your sources, then check the result:

```console
agent-rules apply
agent-rules check
```

`apply` verifies its result and restores affected content if projection or
post-check fails. `check` is read-only and exits nonzero on drift. An empty
source is reported explicitly, not described as installed rules. Edit the
source and apply again to update a rule or skill. Delete a source item and
apply to remove its managed output; other instructions and skills remain.
An existing unmarked skill with the same name causes an error rather than
being overwritten. Links in affected paths are rejected.

## Project configuration

```json
{
  "version": 1,
  "tools": ["claude", "codex"],
  "rules": [".agent-rules/rules"],
  "skills": [".agent-rules/skills"]
}
```

Paths are relative to the project root, one level above `.agent-rules`, even
when the command runs elsewhere. Absolute source paths are also accepted but
are not portable. Init saves project-relative paths where possible; an explicitly
selected source on a different Windows drive remains absolute. Multiple source
directories are combined; duplicate ids,
including rule/skill collisions, are errors. A configured directory must exist
and cannot overlap the generated destinations.

Without `--config`, only the current directory's `.agent-rules/config.json`
is read; parent projects are not searched. To work from elsewhere, pass
`--config path/to/project/.agent-rules/config.json` to `init`, `apply`, or
`check`. Config files must remain inside the project's `.agent-rules` folder;
their filename can differ.

An empty directory means its kind is still managed: stale outputs are removed
on apply. An empty source list (`"rules": []` or `"skills": []`) leaves that
kind untouched. Removing a tool from `tools` likewise stops managing its
locations; it is not an uninstall operation. To remove managed content before
deselecting a tool or kind, apply an empty source directory while it is still
selected. Tools sharing an output such as `AGENTS.md` share its managed namespace.
Configuration files, source text and the project CLI's input/output use UTF-8.

For automation, `init --non-interactive --tools claude codex` uses the default
source directories without prompts. Repeat `--rules` or `--skills` to supply
existing alternatives. Normal use only needs the interactive initializer.

## Existing declaration-based usage

The checkout also remains the live portable source of the maintainer's rules
and skills. The existing commands below retain their checkout-based defaults
and deployment declarations. These advanced inputs are not needed by the
project CLI. Environment-specific topology and private bindings stay separate.

Render the managed rule files into a workspace:

```console
python3 bin/rules.py render <workspace>
```

Verify that a workspace still matches the source rules:

```console
python3 bin/rules.py verify <workspace>
```

`render` writes namespaced Claude rules under `.claude/rules/`, Cursor rules
under `.cursor/rules/`, and OpenCode rules under `.agents/rules/`, preserving
unrelated local overlays. Codex-style rules are written as namespaced managed
sections in `AGENTS.md`. `verify` returns a nonzero status when generated content
is missing, changed, duplicated, or mixed with stale content in the managed
namespace.

Project those same bytes onto a site/workspace declaration. The checkout's
`rules/` and `skills/` are always included; repeat `--rules` or `--skills` only
for additional private sources:

```console
python3 bin/place.py check --declaration PLACEMENT.md
python3 bin/place.py apply --declaration PLACEMENT.md
python3 bin/place.py selfcheck
```

`place.py` takes no machine paths of its own. `--site`, `--workspace`, and `--scope` restrict which
declaration rows apply. `apply` keeps a process-memory snapshot of affected
targets and restores it if the post-check fails.

Discover and start a CLI from the same declaration without an environment-private
launcher:

```console
python3 bin/place.py list --declaration PLACEMENT.md
python3 bin/place.py start --declaration PLACEMENT.md <workspace> <tool> -- <tool arguments>
```

## Environment catalog

OpenCode skill placement uses `.opencode/skills` in a project and
`~/.config/opencode/skills` globally, following its
[native skill discovery](https://opencode.ai/docs/skills). Placement checks prove
bytes and configuration, not that an agent session has read a skill.

A controller may keep a private environment catalog and pass its explicit path
to the same public entry point:

```console
python3 bin/place.py list --catalog rules/environments.json --purpose rule-experiment --json
python3 bin/place.py check --catalog rules/environments.json --environment ubuntu-24 --probe
```

`--catalog` and `--declaration` are separate modes. A catalog has
`schemaVersion: 1`, stable-ID `sources`, and `environments`. Sources name their
origin host and a `paths` map of explicit per-observer readable paths; select an
alias with `ENVIRONMENT_INVENTORY_HOST`, with `windows`, `linux`, and `default`
as conventional keys. An empty `paths` map is intentional for a remote source:
list retains it as `unverified`, while catalog check fails only when that source
belongs to its selected environment. A source is either `placement-tsv` or `json-pointer`.
The latter must declare scalar JSON Pointers in `pointers`; the catalog prints
only those values, never a source document or authentication profile.

An environment names one or more `refs`, allowing several placement sites and
an apparatus JSON source to describe the same environment. It declares
`purposes` (`normal-development`, `rule-experiment`, `product-development`,
`operator`, or `recovery`) and a state (`pending`, `active`, `retained`,
`retired`, or `unclassified`). Active purpose matches are candidates; pending,
retained, retired, and unclassified entries remain visible with their reason.
No fallback selection is made. An `apparatus` entrypoint uses only
`{"kind":"apparatus","paths":{"windows":"...","linux":"..."}}`;
the selected path is read-only checked and reported as unverified when this
observer has no readable path. `agents` may refer to a JSON scalar field or a
placement site field for their runtime principal and config root. For lifecycle
checks, JSON runtime values must match exactly one explicitly referenced site
in the supplied placement declaration. The config root must match that tool's
placement-managed default root; unsupported overrides are rejected before launch.
Entrypoints
are descriptive existing public paths (including an apparatus path), never
shell commands.

Plain `list` only reads local source paths. `--probe` is observational: it may
list WSL distros on Windows or make a batch-only SSH reachability attempt. It
does not start a runtime, request interactive authentication, apply placement,
or alter permissions. `check --catalog` validates schema, references and that
every site in every readable placement source is represented; `--environment`
limits the reported target while still rejecting an unknown ID.

A remote source can declare `probe: {"transport":"ssh","target":"alias",
"configPaths":{"windows":"C:/config/alias.conf"}}` and its absolute remote
`path`. The explicit config file is parsed as data: an exact `Host` block with
hostname, user, port, identity, known-hosts file and connection timeout. Executable
SSH directives and includes are rejected; the probe passes explicit options to
SSH with user/system config disabled and reads only the declared file. An
environment's `connection: {"transport":"ssh","source":"source-id"}` reuses
that source observation. WSL connections may use
`{"transport":"wsl","distro":{"source":"source-id","field":"distro"}}`
to reference a declared JSON field, or
`{"transport":"wsl","distro":{"source":"source-id","site":"S2","field":"host"}}`
to reference a placement site's non-empty string field. Installed/running WSL
observations do not claim runtime reachability; stopped installations remain candidates.
When an SSH runtime is contained by a WSL distro whose name has no existing
placement or JSON source, its SSH connection may carry an optional
`"wslDistro":"Ubuntu-26.04"` string. This catalog-owned outer connection name
is excluded from the full Windows `unregisteredDistros` diagnostic; it does not
replace the SSH target, inner runtime principal, or config root.

`start` accepts only a local `kind=direct` workspace. It verifies every managed
location on that site before resolving the declared tool entry point, then
preserves the child process's standard streams and exit status. For a remote
workspace, run this same public command on the target host. Transport, GUI,
authentication probes, generated wrappers, and environment-specific session
bookkeeping are not launcher functions.

Unrelated rule files and root instructions are outside that namespace and are
left untouched. A malformed unmatched managed marker fails closed; repair that
marker before rendering so the tool never guesses how much local text to
remove.

## Agent configuration report

`bin/agent_report.py` is a standalone Python 3.10+ tool: copy that one file
anywhere to use its built-in Codex, Claude Code and Cursor Agent adapters. It
does not import the renderer, read a placement declaration, or require private
environment code. It asks **new diagnostic sessions** which instruction/config
files and skills they know about, checks reported local paths, and writes one
offline HTML with search, reported-state and path-existence filters.

From the checkout, with the desired CLIs already installed and authenticated:

```console
python3 bin/agent_report.py --output report.html
```

The optional positional argument selects a target directory (default: current
directory). `--output` is required and must name a **new file** in an existing
directory; it never overwrites files. Relative output/plugin/config paths are
relative to the caller's directory, not the target. Repeat `--platform codex`,
`--platform claude`, or `--platform cursor` to select adapters. Without selection,
all registered adapters are checked and installed ones are queried; missing
CLIs are explicitly listed. CLI candidates are resolved in PATH order within
each adapter: `codex`, `claude`, and `agent` then `cursor-agent`, respectively.
`--timeout SECONDS` optionally limits each invocation; there is no default
deadline and the collector never automatically retries. CLI/provider-internal
retries remain their own behavior.

Exit 0 means selected queries returned valid data (possibly partial); exit 1
means at least one query failed or an explicitly selected CLI was unavailable;
exit 2 means invalid inputs/plugin contracts or report-write failure. Missing
auto-detected CLIs do not change exit 0. A report with no installed CLI still
says that no inventory was collected. Version-query failures remain visible
and do not prevent the inventory query.

The report separates **reported state** from **path existence**. `available`
means a skill is catalogued, while `loaded` means its body is reported as already
in context. The prompt forbids opening skills just to enumerate them. The
diagnostic uses visible metadata only, not an independent configuration search
or precedence calculation; configuration values not exposed to the model may
be unknown. Omitted categories become `unknowns`, not empty successes. Missing
item metadata defaults to unknown or an empty path/source. Existence uses
`stat()` as the current user, with relative paths based on the target and `~`
expanded using the inherited home. Non-file sources, foreign paths and access
errors are `not checkable`; a missing path never negates a loading claim.

The built-ins use Codex's read-only sandbox and ephemeral session, Claude's
empty built-in tool set / `dontAsk` / no session persistence, and Cursor's ask
mode. Their diagnostic restrictions are recorded in the HTML. They request no
tool use, file changes, delegation or external calls beyond the model query.
These are **not equivalent to normal interactive sessions**: restrictions can
limit visibility. HOME, configuration environment variables and authentication
are inherited unchanged; settings and permissions are not rewritten. Normal
CLI startup may execute trusted hooks, initialize plugins/MCP servers, refresh
authentication, write caches/telemetry/history, or incur model charges. The
collector cannot sandbox a launcher, plugin or startup hook; use trusted
directories and existing platform policy. It never adds permission-bypass flags.

Only normalized metadata is rendered, with all display strings HTML-escaped
and no external resources. Raw stdout/stderr, exception messages, conversation
events, setting bodies and environment values are not included. Unexpected
schema fields are rejected. This is not a semantic secret scanner: the model
and trusted adapters must obey the metadata-only contract, and filenames or
metadata can themselves be private. Review HTML before sharing; never commit
real-environment reports to this public repository.

### Existing launch entry points

`--launch-config FILE` accepts a JSON object mapping platform IDs to nonempty
argument arrays. An array replaces the executable prefix; the adapter's
version/query arguments are appended without shell expansion. The prefix's
first element resolves through PATH (or may be an explicit executable path).
On Windows, direct `.cmd`/`.bat` launchers are rejected because Windows can
implicitly expand them through `cmd.exe` even with `shell=False`. For a CLI
distributed as an npm shim, configure its existing native `node.exe` and CLI
JavaScript entry point as separate prefix elements, or use a native CLI build.
Arguments are literal: no variable, `~`, placeholder or shell expansion is
performed. Relative executable/argument paths should be avoided: child working
directory is the target. A launcher must forward to the selected product in
that same target and preserve stdout and exit status. The HTML records the
PATH-resolved product candidate and launcher separately; it cannot inspect a
custom launcher's internal executable selection. Keep credentials out of argv.

For environments using the public `place.py start`, first use its existing
`list` command to identify the workspace. A configuration has this shape
(replace the example paths/workspace with that environment's declarations):

```json
{
  "codex": [
    "python3", "/path/to/agent-rules/bin/place.py", "start",
    "--declaration", "/path/to/PLACEMENT.md",
    "workspace-id", "codex", "--"
  ]
}
```

Add the environment's existing `--rules` inputs before the workspace ID when
required. Use the declared workspace's path as the report target: `place.py`
sets its child cwd from that declaration. There is no mandatory launcher or
environment-specific path in the report implementation.

### Report plugin API v1

These are report adapters, separate from any vendor's agent plugin format.
Repeat `--plugin-dir DIRECTORY` to load trusted Python files from explicitly
specified directories. Immediate `*.py` files load in sorted order; files that
resolve outside that directory are rejected. There is no
recursive discovery, cwd auto-loading, dependency installation or download.
The files execute as the current user, so specify only code you trust.
Dependencies and authentication requirements must be documented by each plugin.

Each module exports integer `PLUGIN_API_VERSION = 1` and
`get_platforms() -> list[Adapter] | tuple[Adapter, ...]` (nonempty). An adapter
is any object exposing this interface; no inheritance/import of the report
module is required:

| Member | Contract |
| --- | --- |
| `id: str` | Unique `[a-z][a-z0-9_-]*`; built-ins cannot be overridden |
| `name: str` | Nonempty display name |
| `cli_candidates: list[str]` | Nonempty PATH command names, in preference order |
| `restrictions: str` | Nonempty description of diagnostic restrictions and limits |
| `version_args() -> list[str]` | Arguments appended to executable/launcher |
| `parse_version(stdout: str) -> str` | Version token matching `[0-9][\w.+-]*`, not arbitrary output |
| `query_args(target: pathlib.Path) -> list[str]` | Nonempty arguments, including prompt, for a fresh read-only session |
| `parse_response(stdout: str) -> dict` | Extract final metadata only, reject product errors/incomplete responses |

Metadata/method signatures and generated argument arrays for **all** adapters
are checked before any CLI invocation, even for unselected adapters. Loading
failure, unsupported API, duplicate IDs and invalid implementations fail the
whole invocation before collection. Methods that prepare arguments must be
side-effect-free; only the collector runs CLIs. Return-value correctness of
parsers is checked when real responses arrive, and conversion failures are
isolated per platform. Plugin exceptions must be ordinary `Exception`
subclasses, not process exits. Never include raw CLI output in returned fields.

The common result is a dict with `files`, `skills`, `unknowns` lists. Every
item uses only the string fields `name`, `path`, `source`, `role`, `scope`,
`state`; `name` is required and nonempty. `path` is a concrete local path or
empty; `source` identifies non-file origins. `state` is one of `loaded`,
`available`, `applicable`, `inactive`, `unavailable`, `unknown`. For skills,
prefer `loaded`, `available` or `unknown` as defined above. Example:

```json
{
  "files": [],
  "skills": [{
    "name": "example", "path": "", "source": "session skill catalog",
    "role": "example task", "scope": "session", "state": "available"
  }],
  "unknowns": []
}
```

A minimal adapter for a hypothetical CLI that implements a read-only
`report --metadata-only --json` command returning that schema:

```python
import json

PLUGIN_API_VERSION = 1

class Example:
    id = "example"
    name = "Example Agent"
    cli_candidates = ["example-agent"]
    restrictions = "Read-only metadata report; requires example-agent login"

    def version_args(self):
        return ["--version"]

    def parse_version(self, stdout):
        return stdout.strip()  # CLI must return only its version token

    def query_args(self, target):
        return ["report", "--metadata-only", "--json", "--directory", str(target)]

    def parse_response(self, stdout):
        return json.loads(stdout)

def get_platforms():
    return [Example()]
```

Adapter CLI formats are based on the official
[Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode),
[Claude CLI reference](https://code.claude.com/docs/en/cli-reference), and
[Cursor parameters](https://cursor.com/docs/cli/reference/parameters) /
[JSON output](https://cursor.com/docs/cli/reference/output-format).
Run offline contract, standalone-copy and simulated-CLI tests with:

```console
python3 tests/test_agent_report.py
```

These tests run in the existing Linux/Windows CI. Actual Cursor responses
remain unverified until exercised on a host with an installed, authenticated
Cursor CLI; mock success is not evidence of live compatibility.

Live validation on 2026-09-08 (Linux, Python 3.14.4) used the existing public
launch entry point, Codex 0.153.4 and Claude Code 2.1.263. Both returned valid
partial inventories, including explicit unknowns, and produced HTML tables.
The target's pre-existing instruction/configuration files were unchanged after
the diagnostic. Cursor was unavailable through that environment's launcher;
its failure was isolated and recorded in the same report. Real report data and
launch configuration remain outside this repository. These observations do
not establish completeness of the agents' self-reports or absence of startup
side effects outside the target.

## Push preflight

Every agent must run the shared, read-only decision command after committing,
using the source checkout path supplied by its environment:

```console
python3 <agent-rules>/bin/push_preflight.py <repository>
```

It emits one JSON object with `decision` (`push`, `hold`, or `ask`), a stable
`reason` code, `remote`, and `destination`. Only `push` includes `push_argv`,
which the caller may execute in the target repository. The command never pushes
or changes Git state. A successful decision, including `hold` or `ask`, exits 0;
callers must inspect `decision`, not treat the exit status as push approval.

Pass explicit user instructions as `--user-intent push` or `--user-intent hold`,
documented temporary-save intent as `--temporary`, and explicit repository
classification as `--oss yes` or `--oss no`. Defaults are automatic; neither a
WIP subject nor public visibility alone establishes these facts. Explicit push
bypasses automatic eligibility and topic restrictions, while retaining remote
and destination checks and normal Git history protection.

An environment can supply a private allowlist with `--policy <path>`:

```json
{"default_branch_push_repositories": []}
```

Optional booleans `default_branch_push_private` and `default_branch_push_oss`
authorize all private or all eligible public OSS repositories, respectively;
both default to false. The optional URL array
`default_branch_push_excluded_repositories` defaults to empty and overrides
both individual and category grants, returning `hold` /
`DEFAULT_BRANCH_PUSH_EXCLUDED` for default-branch automatic pushes. Explicit
push still takes precedence. Category grants require explicit user authorization
and preserve the existing visibility/license checks. PR activity is not polled
or interpreted by this helper; any decision to exclude a repository belongs to
the environment's operating policy.

Add repository URLs only when the user explicitly authorizes automatic default
branch pushes for those repositories. For an individual grant, the selected push remote must match an
entry using the helper's existing repository identity rules: the optional
`git+` prefix is removed, then GitHub SSH/HTTPS URLs normalize to one repository
identity; other hosts retain their transport and path spelling. Local paths, remote names,
and wildcard patterns are invalid. A match removes only the default-branch
restriction and returns `DEFAULT_BRANCH_PUSH_ALLOWED`; temporary commits,
repository eligibility, and destination checks still apply. Without category
grants, no policy, an empty list, or an unmatched repository retains the existing behavior. Invalid or
unreadable configured policy returns `ask` / `INVALID_PUSH_POLICY` for automatic
decisions after explicit intent and temporary-commit handling. Explicit push
and hold do not depend on this file. Never omit a configured policy to bypass
an error. The private environment binding supplies its path; rule projection
does not copy the JSON into product repositories.

Git configuration selects the candidate remote before any hosting lookup.
GitHub metadata is read using authenticated `gh`; unsupported hosts, missing
metadata, ambiguous destinations, and unrecognized licenses return `ask`.
Automatic license recognition currently covers OSI-approved
[MIT](https://opensource.org/license/mit),
[Apache-2.0](https://opensource.org/license/apache-2.0),
[BSD-3-Clause](https://opensource.org/license/bsd-3-clause), and
[ISC](https://opensource.org/license/isc). Other licenses require explicit OSS
classification; the helper does not infer approval from an arbitrary SPDX ID.
The helper must be available from the source checkout; rule projection does not
install executables. Do not replace an unavailable helper with an improvised
push decision. See `rules/git-commit-policy.rule.md` for the policy order.

Offline fixtures exercise default and topic branches, upstream selection, forks,
visibility, detached HEAD, and unsafe remote configuration:

```console
python3 tests/test_push_preflight.py
```

## Skills

Rules and skills are the two managed kinds. A rule is always-on text projected
into every tool's rule convention; a skill is a directory the agent loads on
demand. Both are copied from this repository and compared byte for byte, so a
skill that has drifted in one tool is a check failure rather than a silent
difference between tools.

Each `skills/<id>/` directory holds a `SKILL.md` with `name` and `description`
frontmatter, plus whatever else the skill needs. The tree is carried verbatim:
placement metadata lives in the declaration, never in `SKILL.md`, so a skill
vendored from another repository stays diffable against its source. Record such
a skill in `skills/UPSTREAM.tsv` with the upstream repository, ref, path, tree
sha, and license.

A declaration row carries `skills` in its `kind` column to receive them. Adding
a skill means adding a directory here; no declaration or code changes.

Rules and skills share one id namespace. An exception row in the declaration
names an id and a location, and the location is what says which kind it means,
so a rule and a skill answering to the same id is a check failure.

Each projected skill directory gets an `.agent-skills` marker naming the skill.
A rule file is reclaimable because its name carries the `agent-rules--` prefix,
but a skill directory has to keep the name the agent invokes, so the ownership
claim goes inside it. Directories without the marker were placed by hand and are
never touched.

Publish the skills written here to a separate public checkout:

```console
python3 bin/place.py mirror --skills skills --dest <checkout> [--check]
```

A skill listed in `UPSTREAM.tsv` is someone else's work; it is managed here so
every tool gets the same bytes, but the mirror carries only what is written
here. The manifest is required and begins with its header row, even when it
lists nothing: publishing stops when it is missing, has lost the header, or
names a skill this repository no longer holds, because a manifest that cannot
be read would otherwise pass for one that reports no vendored work.

## Inventory checks at normal start

An environment owner can bind a declaration's sites to inventory validation.
Add an `INVENTORY` TSV section with `site`, `catalog`, `environment`, and
`evidence` columns. Paths are relative to the declaration, unless absolute.
For example, a row `local`, `environments.json`, `development`,
`session-evidence.json` binds the `local` site to that catalog environment.
Every site started from a declaration containing this table needs a binding.

`place.py start` checks the binding before invoking the CLI. It requires an
active environment, registered installed tools, the management skill and reading
binding, unchanged managed placement, matching runtime identity/config roots,
and external initial-reading evidence. Missing evidence and pending state reject
normal start. There is no normal-start bypass option. Existing check/apply remain
available for repair.

Setup integrations call the same public
`inventory_lifecycle.validate_lifecycle` function in construction mode, passing
the constructing agent, explicit declaration, placement context, and actual
runtime identity. Pending construction may lack initial-reading evidence but
must have the constructing agent's skill and binding. This helper does not
perform a state transition or launch anything.

Evidence is an external JSON array. Each entry identifies the descriptor,
`session` (`continuing` or `startup`), ISO `observedAt`, `skillId`, observed
`condition`, `applied: true`, `environmentId`, `declarationSha256`, runtime
`principal` and `configRoot`, and the
SHA-256 values `skillSha256`, `bindingSha256`, and `recordSha256`. `record` points
to an actual session observation record; relative paths resolve against the
evidence file. The skill hash covers SKILL.md source bytes; the binding hash
covers the parsed rule body. Keep real session records outside version control.
These references make stale or missing evidence detectable; they do not prove
the truth of an observation or enforce subsequent model behavior.

Deploy a binding only through the environment's existing setup and reviewed
adoption flow. An unbound declaration retains the independent project's normal
placement behavior; adding this public capability does not enroll a project in
the maintainer's inventory policy.

## Source format

Each `rules/*.rule.md` file contains frontmatter with `id`, `title`, and
`summary`. `tools` is optional: omit it to place the rule for every CLI, or
list CLI ids to restrict it. The body is shared policy text; optional
tool-specific bindings are selected by `placement.json`. `placement.json`
names file conventions and the CLIs that read them. Codex-style sections use
the managed markers generated by `bin/rules.py` and should not be edited by
hand.

The catalog was derived from an evaluated private candidate, then reconciled
and sanitized for portable use. Private experiment history and environment
topology are not part of this repository.

On POSIX, skill placement and mirroring preserve each file's execute bits and
check reports execute-bit drift, even when its bytes match. Other source mode
bits (including setuid, setgid and sticky bits) are not copied. On Windows,
only file contents are compared; POSIX execute bits are not managed.

## Package development and publication

In a development Python environment, from this checkout root:

```console
python -m pip install build twine
python -m build
python -m twine check --strict dist/*
```

`build` produces an sdist, then builds the wheel from that sdist. The wheel
contains the shared engine and tool conventions, not the maintainer's rule or
skill catalog. The old script layout is also the package layout, so there is
one projection implementation and existing standalone script consumers keep
working.

Install the wheel into a separate clean virtual environment and use that
environment's Python to run `tests/test_project.py`. Run `agent-rules --version`
and `agent-rules --help` from its installed entry point as well. No editable
install or `PYTHONPATH` setting is needed. CI performs these checks on Windows
and Linux, along with the existing regression checks:

```console
python3 tests/test_rules.py
python3 tests/test_push_preflight.py
```

The test renders and verifies a temporary workspace, confirms that drift is
rejected, then re-renders and verifies recovery.

Before publishing, confirm ownership and availability of the PyPI name
`agent-rules`, the release version and license metadata, passing CI, and the
contents of both distribution files. Name availability is not established by
this repository. If the name cannot be used, choose a distribution name before
publication and update its metadata, version lookup and installation examples
together; the console command can remain `agent-rules`.

Publication requires a separate explicit release decision and a configured
PyPI publishing identity. Only then upload the reviewed distribution files
with Twine, verify the installed version from PyPI in a clean environment,
and update the publication-status paragraph above. Do not add tokens to this
repository or automatically publish on pushes. This change does not create
tags, GitHub Releases or PyPI releases.

## Registered work and branch enforcement

`python3 bin/place.py branch --help` exposes the local Git integration. It uses
only this public source, the selected Python runtime and repository-local Git
configuration; no private launcher or personal path is required. Git must support
`reference-transaction` hooks and `rev-parse --path-format` (Git 2.31 or newer).
The runtime needs Python 3.10 or newer. Git for Windows supplies the shell used
by the fixed dispatcher. Keep the public source available after installation.

Install with `branch install --repo REPO --remote REMOTE`. This verifies the
remote default via `ls-remote --symref`, preserves existing hooks and installs the
fixed `hooks/branch-hook` bytes for `prepare-commit-msg`, `reference-transaction`
and `pre-push`. `agentBranch.python`, `agentBranch.source` and `core.hooksPath`
are explicit local configuration. Existing hooks retain arguments, input and
exit status. A collision that cannot be preserved is rejected. Install can retry
an interrupted owned installation; unknown files are never overwritten. Re-running
install from a reviewed public checkout rebinds the Python source and runtime
while preserving registrations and hook bytes. Before updating the checkout that
supplies its own hooks, rebind from a separate reviewed source so its source hash
remains stable during the merge. A changed dispatcher needs a separately reviewed
hook migration; it is never silently overwritten.

Register existing integration and topic checkouts with `branch begin --mode
adopt --repo REPO --task ID --request REQUEST --branch BRANCH --worktree PATH
--base COMMIT --into DESTINATION`. Paths are absolute. `REQUEST` references the
existing user requirement or issue; it is not a duplicate progress ledger.
`COMMIT` is the explicitly reviewed historical starting point and must agree
with the remote history. The default branch is registered with itself as its
integration destination. No historical commits before adoption are retroactively
classified as violations. Unregistered retained branches remain untouched; their
future updates are refused.

For independent work use `branch begin --mode new --repo REPO --task ID
--request REQUEST --branch TOPIC --worktree NEW_PATH`. Fetch the remote default
first; the command verifies that the fetched commit still agrees with the remote.
It creates a new topic and worktree using standard Git. `--into BRANCH` defaults
to the verified remote default. For dependent work add `--depends-on PARENT_ID`;
the parent tip becomes the starting point. Reuse existing work with `branch begin
--mode continue --repo REPO --task ID`. A mismatched branch, path or common Git
directory is rejected. Interrupted worktree creation is resumed without reset,
stash or automatic removal. Each worktree has one lead performing Git updates.

A fetched update of the **same** remote branch can be admitted with `begin
--mode continue --task ID --repo REPO --sync`, then `git merge --ff-only
REMOTE/BRANCH` in its registered worktree. The one-use import is pinned to the
old and fetched new commits; unrelated fast-forwards are rejected. This does not
identify which Git command produced the same reference transition.

Prepare integration in the registered destination with `branch prepare-merge
--repo DESTINATION_PATH --task SOURCE_ID`. Merge with `git merge --no-ff
--no-commit SOURCE_BRANCH`, run the project's required verification, then commit.
Both tips and the ordered parents are checked again. A dependent task can be
integrated only after its parent has been integrated into the destination's
history. A moved source or destination requires fresh preparation. A successful
integration consumes the permission. A failed or interrupted commit preserves
changes and can be retried; a source reserved by a prepared integration must wait
for that integration to finish or retry.

A user-approved cherry-pick exception is registered in its destination topic with
`branch allow-cherry-pick --repo PATH --commit SOURCE_SHA --approval USER_REFERENCE
--reason REASON`. Each permission is pinned to the current destination HEAD and
one source commit, and is consumed after success. For a sequence, each current
source needs its own applicable exception; a rejected later pick preserves
already committed earlier picks. Conflict resolution does not broaden approval.
Default-branch ordinary commits, unregistered reference updates, unrelated merges,
amend and unauthorized fast-forwards fail before the reference is committed,
including `git commit --no-verify`. Existing approval requirements for history
rewrites remain in force; this interface does not grant rewrite permission.

`branch check --repo PATH` explains inconsistencies and exits nonzero; `--json`
provides machine output. It checks worktree ownership, tips, dependencies, public
source and installed hook bytes and executable state. Registration, commit
permits and integration receipts live in the Git common directory's
`agent-branches/state.json`, shared by linked worktrees. OS locks and atomic
writes serialize registry changes. On another clone/host, register the same work
ID against that clone's remote history; never copy local operation permissions.
The shared push preflight applies the same branch/tip check to installed repos,
then retains its existing visibility, destination and history-protection policy.
The actual pre-push hook checks all submitted refs and commits.

These are accidental-misuse guards, not an isolation boundary against deliberate
Git configuration changes. In particular, a missing hook cannot execute itself:
remaining hooks, `branch check` and the common push preflight detect the missing
file. Deliberately bypassing all these entrypoints is prohibited by policy.
Changes produced by `cherry-pick --no-commit` cannot be attributed after the fact.
The lead still judges functional relationships and the validity of verification.
See the [Git hook contract](https://git-scm.com/docs/githooks) and
[cherry-pick contract](https://git-scm.com/docs/git-cherry-pick).

Run `python3 tests/test_branch_management.py` and
`python3 tests/test_branch_recovery.py` for isolated real-Git tests, in
addition to the existing rules, push preflight and installed-package checks.
The Linux/Windows CI matrix runs the same test. CI results do not establish
installation or behavioral acceptance on an operator's actual host.

## License

MIT. See `LICENSE`.
