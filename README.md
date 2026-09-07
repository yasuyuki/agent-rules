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

Project those same bytes onto a private site/workspace declaration:

```console
python3 bin/place.py check --declaration PLACEMENT.md --rules rules --skills skills
python3 bin/place.py apply --declaration PLACEMENT.md --rules rules --skills skills
python3 bin/place.py selfcheck
```

`place.py` takes no machine paths of its own. Repeat `--rules` for a second
rule directory. `--site`, `--workspace`, and `--scope` restrict which
declaration rows apply. `apply` keeps a process-memory snapshot of affected
targets and restores it if the post-check fails.

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
