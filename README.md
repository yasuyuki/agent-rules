# Agent Rules

Portable source rules and skills, and a deterministic renderer for Claude Code,
Codex, Cursor Agent, Antigravity, and OpenCode workspaces.

This repository is the live portable source of truth for the maintainer's
environments. Environment-specific topology and private bindings are managed
separately.

## Requirements

- Python 3.10 or newer

## Usage

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

## Development

```console
python3 tests/test_rules.py
```

The test renders and verifies a temporary workspace, confirms that drift is
rejected, then re-renders and verifies recovery.

## License

MIT. See `LICENSE`.
