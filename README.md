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
to reference a declared JSON field. Installed/running WSL observations do not
claim runtime reachability; stopped installations remain candidates.
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

## License

MIT. See `LICENSE`.
