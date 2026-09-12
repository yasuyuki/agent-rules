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

For repeated local starts, save the selected inputs once from the directory
where you launch. The public operation validates the declaration and source
directories before publishing the complete configuration:

```console
python3 bin/place.py save-start-config --declaration PLACEMENT.md --rules private-rules --skills private-skills
```

Then use `python3 bin/place.py start <workspace> <tool>` and append native CLI
arguments after `--`, including the CLI's own resume command. Paths in this file
are relative to its directory. `--rules` and `--skills` may be omitted; the public
sources remain included. Optional `--inventory-host` selects the catalog's
existing observer and must agree with an already set `ENVIRONMENT_INVENTORY_HOST`.
`--config PATH` explicitly selects a different file. No parent directory or HOME
is searched. A full `--declaration` invocation ignores the default file; mixing
config inputs and explicit source arguments is rejected. Saving identical inputs
is a byte-preserving no-op. A different or malformed existing configuration is
refused; it is never replaced or repaired automatically. Use an explicitly named
new `--config PATH` for a different set of launch inputs. Configuration does not
apply placement or adopt sources: start still checks the selected workspace/CLI
and current managed bytes before launching it.

## Environment catalog

Grok Build uses the native `grok` executable, `~/.grok/AGENTS.md`, and
`~/.grok/skills`; its workspace locations are `AGENTS.md` and `.grok/skills`.
`GROK_HOME` is its config-root override and must agree with the declared runtime
for lifecycle checks. Grok also discovers Claude and Cursor compatibility files;
use `grok inspect` in the actual workspace to check source discovery and avoid
duplicating managed rules through multiple owners. Inspect is configuration
evidence, not proof of successful agent work. See the official
[rule discovery](https://docs.x.ai/build/features/project-rules) and
[skill discovery](https://docs.x.ai/build/features/skills-plugins-marketplaces).
Use an already registered worktree and native resume arguments after `--`.
The placement entry does not enable Grok's worktree creation or automatic approvals.

For an additional CLI, first add its reviewed descriptor and declaration
locations. To publish the missing agent registration, run the declaration operation
from the registered topic checkout that tracks both `PLACEMENT.md` and its
catalog. It validates the selected site, tool, locations, and catalog source,
then adds only that registration and sets the environment to `pending`:

```console
python3 bin/place.py inventory declare-agent --declaration PLACEMENT.md --site SITE --tool grok
```

Its JSON result records the registered base revision, task, catalog path,
environment, tool, and whether bytes changed. It does not inspect a target
runtime, install or project files, stage, commit, or perform Git operations.
The declaration and catalog must initially match the registered `HEAD`; an
exact prior uncommitted result of this same operation is the sole idempotent
exception. Save, integrate, and push that declared change through the normal
registered branch workflow. This operation does not certify other consumers;
update affected consumers before publishing a descriptor they cannot read.

On the selected runtime, use its existing untracked saved launch inputs:

```console
python3 bin/place.py inventory adopt --config placement-start.json --site SITE
```

`adopt` verifies the catalog against its repository's `HEAD`, records pending in
that existing config, applies the selected site, checks every registered CLI's
readiness, and inspects Grok discovery in the declared direct workspaces without
running a model or changing trust. Only success records active. Failure retains
pending and the catalog is never rewritten. An exact active repeat verifies
readiness/discovery without repeating projection or writing the config. Stale
inputs, a failed check, or changed Git HEAD prevent normal config-based startup.
The config becomes version 2 with one adoption member; no catalog copy or receipt
registry is created. Tracked start configs cannot store runtime adoption.
Like the existing user-owned catalog and public startup code, this detects stale
or incomplete operations; it is not tamper-proof attestation against that same
user editing their state or code. It grants no root or transport authority.

`--source-ref REVISION` explicitly selects the **catalog** repository revision
when a retained runtime HEAD is older. The catalog must match that revision's
checkout representation, including Git EOL rules. An in-repository declaration
must match it too. An explicitly configured external runtime policy, such as a
root-owned deployed declaration, is recorded separately by path and digest;
`sourceScope: catalog` does not claim that policy is a Git blob. The runtime HEAD
and committed catalog revision are both reported. Other dirty files are preserved
and are not attributed to this operation. Normal Git synchronization is still
required to migrate any remaining unrelated legacy state.

The existing `start --config` (or implicit `placement-start.json`) checks the
adoption's exact environment, site, catalog, policy, source inputs, runtime identity
and HEAD. A pending catalog requires this saved adoption; explicit declaration-only
startup cannot infer it. Catalog listing remains declaration-only and does not
claim another runtime's active state. A host bootstrap that previously used only
an explicit declaration must be updated to consume the same saved inputs before
adopting this path. Legacy active catalogs and `prepare-agent`/`activate` remain
compatible for consumers not yet migrated; they still mutate the catalog and are
not the normal versioned declaration workflow.

The returned `commandElapsedSeconds` measures only this command. The 60/120 second
application targets also include controller preparation, Git/shared saving, and
result return. No target-time success or model behavior follows from command success.

Pass the same additional `--rules` and `--skills` sources to declaration operations
when the declaration uses private inputs. `prepare-agent` resolves the catalog,
environment, principal, and config root from the site's `INVENTORY` binding; it
registers the CLI and writes `pending` together. It does not install or start a CLI.
Perform the official installation and any necessary login while pending, using
the environment's existing maintenance route. `activate` runs full readiness
for every registered CLI before writing `active`; it does not accept workspace
or scope restrictions. Then verify behavior through ordinary `start`.

Use the same operation to resume after a failure. Existing exact registration
is preserved; conflicting registration, unrelated runtime identity, and stale
inputs are refused. Failed activation leaves pending. Other environments and
unknown state are retained. Catalog saves serialize cooperating writers with a
native lock plus an atomically published shared claim, including Windows/WSL
writers to the same file. An interrupted owner can resume from the same environment
binding after its native lock is released. A claim from another environment must
be resumed there; a missing owner is not permission to delete the claim. Environment
IDs must identify their actual runtime, not be reused for independent clones.
Saves compare the original bytes before replacement; normal start still checks current
placement after activation. These operations do not make arbitrary source editors
transactional, and do not atomically install a CLI and all its placement files.
Do not hand-edit operational JSON to bypass a refusal.

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
hostname, user, port, identity, known-hosts file and connection timeout. After
config values and inline probe fields are combined, `user`, `port`, `identityFile`,
`knownHosts` and `connectTimeout` must all be explicitly non-empty; missing values
are rejected before SSH runs. Inline `target` remains the fallback when the
config omits `HostName`. Executable
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

`start` accepts only a local `kind=direct` workspace. When the site has an
inventory binding, it requires an active environment and verifies the selected
CLI's registration, runtime identity, effective config root, and required
placement. A broken placement for another registered CLI does not block this
normal start. For a remote
workspace, run this same public command on the target host. Transport, GUI,
authentication probes, generated wrappers, and environment-specific session
bookkeeping are not launcher functions.

Unrelated rule files and root instructions are outside that namespace and are
left untouched. A malformed unmatched managed marker fails closed; repair that
marker before rendering so the tool never guesses how much local text to
remove.

## Work classification

Classify declared work without probing, launching, installing, connecting, or
writing to an environment:

```console
python3 bin/place.py classify --catalog tests/fixtures/work-classification/catalog.json --work tests/fixtures/work-classification/work.json --prefer-environment isolated --json
```

Those fixture files are synthetic and runnable from this checkout; private
catalogs and work inputs belong outside the public repository.

The work document has `schemaVersion: 1` and a `work` array. Each ordinary item
has a stable `id`, a source-record `reference`, and one or more phases. A phase
requires `id`, `summary`, `purpose`, `requires`, and `executor`; it may include
`environment`, `prerequisites`, `acceptance`, and `handoffs`, which default to
empty values. `purpose` uses the catalog purposes; `requires` is an array of
capability IDs; and `environment` is
`{"ids":["optional-host-lock"],"mode":"normal|construction|repair"}`.
An explicit ID permits a retained environment; a pending environment is usable
only for construction or repair. Retired and unclassified environments are
never eligible. `executor` is
`{"kind":"agent|human|ci|external","state":"ready|hold|waiting|unspecified"}`
and may include boolean `required`. The last three fields are arrays of strings.
An excluded item instead has `id`, `reference`, and `excludedReason`; it has no
phases. This preserves why old or completed records did not become work.

Catalog environments may add a `capabilities` object. Each capability ID maps
to `status` (`available`, `preparable`, `unavailable`, or `unknown`), `reason`,
required string-array `evidence`, and, for `preparable`, a `preparation` route.
Omitted capability data means unknown; it never means unavailable. The result
lists every environment candidate, technical classification, preparation,
unmet conditions, and readiness separately. An executor hold or an unreadable
source therefore does not change a declared technical capability into an
unavailable one. A `--prefer-environment` sorts that environment first but
never relaxes a phase's purpose, state, host lock, or capability requirements.
With `--prefer-environment`, a phase's top-level `classification` is relative
to that preferred environment; `proposedEnvironment` is separately selected
only from available or preparable eligible candidates. Unknown candidates stay
visible but never become a positive proposal. Each assessment includes the
capability evidence used for its reasons.

An observer that cannot read a referenced WSL source retains that environment
as unverified. A malformed reference remains an error when its source is
readable. This lets another environment still be listed while making the
missing evidence visible to classification and catalog checks.

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

When a successful query cannot be converted, its existing `response conversion
failed` status remains a failure and the report/console add one fixed diagnostic
stage and code. Built-in envelope failures use `envelope` with `malformed`,
`failed-result`, or `incomplete`; metadata JSON failures use `metadata` with
`malformed-json` or `missing-json`; schema failures use `schema` with a fixed
validation code; other adapter or local processing failures use
`processing: unexpected-error`. These labels contain no response, stderr,
exception text, payload, or traceback. They describe that one query only and
do not save it or trigger a retry.

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

`skills/create-verification-skill/SKILL.md` creates a project-specific verification
skill when generation or revision is requested. Read it by path and name the
target checkout; ordinary verification requests use the existing generated skill.
The workflow is agent-neutral and reuses the project's own operation tools.

`skills/verify-agent-rules/SKILL.md` is the demonstrated output for this project.
It drives public declaration-based apply/check against disposable inputs, checks
actual generated contents and hand-written-file preservation, and retains evidence
after cleanup. Its optional `--environment-repo` profile also proves composition
with agent-environment's synthetic input and disposable agent-skills mirror output.
See [acceptance and limitations](docs/verification-skill.md).
From this checkout root:

```console
python3 skills/verify-agent-rules/scripts/verify.py --repo .
python3 tests/test_verification_skill.py
```

The adapted generator retains pstack's MIT notice and a pinned `UPSTREAM.tsv`
entry. Existing `place.py apply/check` distributes both skills. The existing
authorship-filtered `mirror` excludes that adapted third-party generator and
publishes the original project verifier; use the generator's canonical source
here. Neither skill requires this repository's private environment bindings.

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

## Inventory readiness and normal start

An environment owner can bind a declaration's sites to inventory validation.
Add an `INVENTORY` TSV section with exactly `site`, `catalog`, and `environment`
columns. Paths are relative to the declaration, unless absolute. For example,
a row `local`, `environments.json`, `development` binds the `local` site to
that catalog environment.
Every site started from a declaration containing this table needs a binding.

Use readiness after changing a CLI, placement, connection, or environment
declaration:

```console
python3 bin/place.py check --declaration PLACEMENT.md --site local --readiness
```

Readiness is read-only. It resolves catalog and environment from the selected
`INVENTORY` row and checks pending or active environments across every registered
CLI: principal, config root, referenced site, required placement, managed bytes,
and visible supported CLIs missing from registration. It rejects `--workspace`
and `--scope` because it is an environment-wide check. It does not launch a CLI
or update state. The normal transition is `pending` → repair → readiness passes
→ `active` → behavioral acceptance through the ordinary CLI entry point.

`place.py start` checks only the selected CLI's active binding and required
placement before invoking it. It does not read session evidence or compare
historical hashes, and another CLI's placement defect is reported by readiness
rather than blocking the selected CLI.

Setup integrations may call the same public
`inventory_lifecycle.validate_lifecycle` function in construction mode, passing
the constructing agent, explicit declaration, placement context, and actual
runtime identity. Pending construction must have the constructing agent's skill
and binding. This helper does not
perform a state transition or launch anything.

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
python3 tests/test_inventory_adoption.py
python3 tests/test_inventory_inspection.py
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

Installation protects linked worktrees containing the source or Python runtime
with Git's native worktree lock before pinning bytes. Existing locks are kept;
rebind never unlocks an old dependency because other repositories may still use
it. Legacy installations using an unlocked linked dependency must reinstall the
reviewed source before acceptance. Dependency decommissioning is explicit
maintenance after its consumers have moved, not part of ordinary task retirement.
Primary checkouts are already excluded from retirement.

Installation disables automatic reference packing in this repository with
`maintenance.pack-refs.enabled=false` and `gc.packRefs=false`; other maintenance
remains enabled. Git's hook interface cannot distinguish pruning a loose reference
from deleting the branch itself. `git pack-refs --all --no-prune` is supported;
reference pruning remains rejected. This preserves branch-deletion protection
without a maintenance wrapper or a hook bypass.

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
history, or directly into that parent when it is the registered destination
(its pinned HEAD already supplies the dependency). A moved source or destination requires fresh preparation. A successful
integration consumes the permission. A failed or interrupted commit preserves
changes and can be retried; a source reserved by a prepared integration must wait
for that integration to finish or retry.

Transparent normal operation is a design and acceptance requirement for this
branch workflow, as explicitly requested for this work. Setup inventories,
migration checks and incident repair must not become routine prerequisites for
starting, resuming or finishing work. The owning layer resolves routine targets,
checks consistency and records state using existing registrations and entry
points. Keep safety checks at the protected operation and revalidate after
relevant state changes; do not require repeated history reconstruction, complex
argument assembly, explanations or duplicate records. Verify affected normal
paths with representative operations, without adding per-task reports. This
requirement does not extend this tool's responsibility or authority boundaries.

Retirement is enabled only for work created by the dependency-protecting version
of `begin --mode new`. Existing and adopted registrations are retained: older
consumers may not have locked their source or runtime worktrees. Reinstallation
alone does not certify their migration, and continuation does not silently lift
this restriction. Resolving those legacy dependencies is separate migration work;
do not unlock dependencies or edit registration state to bypass it. An interrupted
or failed installation may leave its newly acquired dependency lock in place;
this is deliberate preservation until explicit maintenance resolves its consumers.

Close a finished registration with `branch retire --repo REPO --task ID`. It
removes the registered worktree and drops the registration; the branch and its
commits are kept. "Finished" means the ledger's integration receipt, not
`git branch --merged`: the receipt's source must equal both the registered tip
and the branch's current commit, and its merge commit must be an ancestor of the
registered destination. Work integrated into a registered topic is finished even
though it never reached the default branch, and a branch merged somewhere else is
not. Retirement is refused for the default-branch registration, the repository's
own working tree, the checkout the command is run from, a checkout holding the
registered `agentBranch.source` or `agentBranch.python`, work another
registration depends on or integrates into, a branch with an outstanding permit,
prepared integration or cherry-pick exception, and a checkout with uncommitted,
untracked or ignored files. Ignored files count because a retired checkout can
contain another repository's registered worktree. Removal uses `git worktree
remove` without `--force`; nothing is reset, stashed or force-deleted, and a
refusal leaves both the registration and the files as they are.

The work identifier, branch name and path become available for new work. The
retained branch is now unregistered, so its future updates are refused like any
other retained branch; re-register it with `git worktree add PATH BRANCH` and
`begin --mode adopt`. Branch deletion is not part of this command. An interrupted
retirement is completed by running the same command again: worktree removal is a
no-op once the directory is gone, and a stale administrative record is pruned
(metadata only, never a file, and repository-wide). There is no bulk mode, no age
or count criterion and no abandonment path; each retirement names one work
identifier and is justified by that work's own integration receipt.

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
The actual pre-push hook checks all submitted refs and commits, and compares its
transport URL with the single effective push URL for the registered remote.
Both branch and tag pushes require the registered fetch repository identity.
Read/write URL separation is supported for equivalent GitHub transports and
native absolute paths/local file URLs; unknown transports remain exact matches.
Different repositories, remote names and multiple destinations are rejected.

To publish an explicitly requested release tag, first create the local tag, then
register `branch allow-tag-push --repo PATH --remote REMOTE --tag TAG_NAME
--commit FULL_COMMIT_SHA --approval USER_REFERENCE`. The tag name is relative to
`refs/tags/`; the commit must be a full object ID. The command requires a
registered checkout and pins the tag's raw object (including its annotation),
peeled commit, remote name and URL. Both lightweight and annotated tags work.
Exactly one fetch URL and one push URL must identify the registered repository;
the approval additionally pins the exact effective push URL. The remote tag must
not exist. Publish with `git push REMOTE refs/tags/TAG_NAME`.

The hook admits only creation of that exact tag at that exact destination.
Changed tags, tag replacement/deletion and unapproved refs in the same push are
rejected. After the whole batch passes, the hook consumes each tag permission
before transport, because pre-push cannot observe the server's final result.
A transport failure or `--dry-run` therefore needs re-registration before a
retry; reuse the same approval reference only while its scope still applies.
This does not authorize history rewriting or bypass the existing branch checks.

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


## Cross-environment handoff

The maintainer's `handoff` rule keeps workspace resumption in the nearest
HANDOFF.md and cross-environment unfinished work in an explicitly selected,
accessible shared task. `classify-work` handles capability/phase routing;
`human-handoff` handles a person's relay and copy/paste path. The session-end
rule includes that relay as human work. The phase rule already preserves scope
and acceptance boundaries and needs no parallel delivery procedure.

This uses existing issue/task storage and notification paths. No task database,
mandatory handoff CLI, credential transfer or delivery service is introduced.
Saving or rereading a task is not recipient receipt; sender completion is not
acceptance of remaining work. Missing source documents and sender-only artifacts
remain blockers to the affected handoff, with source information retained.

Behavioral regression cases and response grading are in
[the handoff fixtures](tests/fixtures/handoff/README.md). Run:

```console
python3 tests/test_handoff.py
python3 tests/test_rules.py
```

The offline test validates the regression grader, not agent compliance. Exercise
fresh sender/receiver sessions with the fixture protocol to measure behavior.
Synthetic cases cannot establish real cross-host delivery or UI clipboard
fidelity. For real acceptance, use an independent harmless task, an authorized
existing destination and fresh sender/recipient sessions; retain the shared
reference, source revision, actual receipt and acceptance results separately.
Unavailable destination execution must be handed over, never marked passed.
Rule/skill placement and mirroring use the existing `place.py apply/check/mirror`
commands; a successful byte check is not a behavioral acceptance result. Do not
apply these source changes to pinned experimental baselines or reuse previous
experiment results as evidence for the changed instructions.
