# User manual

Use the [README](../README.md) to install from source. The project CLI manages
your own sources. The advanced checkout commands below additionally support the
maintainer's catalog and explicitly supplied environment declarations; they do
not enroll an ordinary project in that environment policy.

## Project rules and skills

Run `agent-rules init` in the target project, select tool IDs from its prompt,
and choose source folders. Accepting the defaults creates empty
`.agent-rules/rules/` and `.agent-rules/skills/`. Enter `-` to leave a kind
unmanaged. No agent is launched, authenticated, or given sample policies.

For a first rule, save `.agent-rules/rules/project-style.rule.md`:

```markdown
---
id: project-style
title: Project style
summary: Follow this project's documented conventions
---
Follow the conventions in this project's README.
```

Run `agent-rules apply`, then `agent-rules check`. Apply verifies its output and
restores affected content on failure; check is read-only and fails on drift.
Edit the source to update policy. Delete an item and apply to remove its managed
output. Unrelated instructions and unmarked skills are preserved; a colliding
hand-written skill or a link in an affected path is refused.

A skill is an on-demand directory, unlike an always-on rule. Save
`.agent-rules/skills/project-review/SKILL.md` with `name: project-review` and a
`description` in frontmatter. Its name must match the directory; supporting
files are copied with it. Rules and skills share a unique ID namespace.
Use relative references within the skill so a distributed copy works alone.

### Configuration and removing managed content

The initializer's `.agent-rules/config.json` can combine multiple source folders:

```json
{
  "version": 1,
  "tools": ["claude", "codex"],
  "rules": [".agent-rules/rules"],
  "skills": [".agent-rules/skills"]
}
```

Relative paths start at the project root, not the command's working directory.
Keep sources distinct from generated destinations. Absolute paths work but are
not portable. From another directory select the config with `--config`; parent
projects are not searched. For automation, use `agent-rules init --help` for
noninteractive tool/source selection. Configuration and source text use UTF-8.

An **empty source directory** remains managed and removes stale output on
apply. An **empty source list** leaves that kind untouched. Removing a tool
from the config likewise stops managing it; it does not uninstall its output.
To remove managed content, apply an empty directory while the tool and kind are
still selected, then deselect them. Tools sharing `AGENTS.md` share that managed
namespace. Unsupported artifact kinds are reported rather than silently placed.

## Declared placement and source authoring

Run checkout commands from the source root with its Python environment active.
`python bin/place.py --help` is the command index; subcommand help gives arguments.
Uppercase arguments below denote values from your own reviewed declaration.

Use declaration-based placement when a controller owns multiple sites,
workspaces or home locations. Start from the structure in the
[synthetic declaration](../tests/fixtures/place/declaration.md), replacing its
fixture locations before applying. `SITES` identifies hosts/homes, `WORKSPACES`
their roots, `LOCATIONS` the required or absent rule/skill destinations, and
`EXCEPTIONS` the deliberate deviations. A location's `kind` selects rules or
skills. Keep environment paths and private bindings in your own declaration.

```console
python bin/place.py check --declaration PLACEMENT.md
python bin/place.py apply --declaration PLACEMENT.md
```

This mode includes the checkout's `rules/` and `skills/`; repeated `--rules` and
`--skills` add other sources. Use the project CLI instead if you want only your
own policies. Site/workspace/scope filters limit the selected rows. Apply restores
affected targets if its post-check fails; check compares managed bytes with source.

Rule frontmatter requires `id`, `title`, and `summary`. An optional `tools` list
restricts consumers; tool-specific `<!-- binding: TOOL -->` sections add their
text to shared policy. [placement.json](../placement.json) is the authority for
tool IDs, file layouts and supported artifact kinds. The
[source loaders](../bin/rules.py) validate names, metadata and collisions.
Edit these sources, never managed sections or distributed copies. Malformed
managed markers must be repaired before projection can proceed.

For rule-only workspaces without a site declaration, the existing
`python bin/rules.py render WORKSPACE` and `verify WORKSPACE` operate on the same
catalog and namespaced outputs. Unrelated local overlays stay outside ownership.
POSIX skill copies retain execute bits; Windows checks contents without claiming
POSIX mode management. Placement proves matching files, not native agent loading.

### Original and third-party skills

A projected skill's `.agent-skills` marker establishes ownership. Unmarked
same-name directories are hand-written and cannot be overwritten. For vendored
skills, retain licenses and record provenance in `skills/UPSTREAM.tsv`; placement
copies their complete trees without modifying the upstream content.

To generate an original-work-only mirror, use `python bin/place.py mirror --help`.
`mirror --skills skills --dest DESTINATION` writes a separate checkout, and
`--check` compares it with source. The required upstream manifest excludes
third-party skills. The mirror owns its `skills/` subtree, not unrelated root
files; use a dedicated destination. Generation does not commit, publish or deploy.

The original skills cover work classification, environment inventory, human
handoff, document optimization and project verification. The vendored
[generator](../skills/create-verification-skill/SKILL.md) is for creating or
revising a verification skill; use the existing
[verifier](../skills/verify-agent-rules/SKILL.md) for an ordinary run.
[Acceptance evidence](verification-skill.md) distinguishes those operations and
historical demonstrations from current success.

## Launch and environment maintenance

Discover the declared entry before starting an installed, authenticated CLI:

```console
python bin/place.py list --declaration PLACEMENT.md
python bin/place.py start --declaration PLACEMENT.md WORKSPACE TOOL
```

Append native CLI arguments after `--`, including resume arguments. Start runs
on the target host and supports local direct workspaces; transport, GUI opening,
authentication and experiment lifecycle remain with their existing owners.
It checks the selected CLI's placement and, when inventory-bound, active runtime
identity. Another CLI's broken placement does not block this selected CLI.

For repeated starts, `save-start-config` validates and saves the explicit inputs
in `placement-start.json` in the launch directory. Then `start WORKSPACE TOOL`
reuses them. Additional private sources must be included when saving; `--config`
selects a different file. No HOME or parent search supplies hidden inputs.
Saving configuration does not apply placement or adopt a runtime. A different
existing configuration is not overwritten: select an explicit new config or
resolve the existing one through its owner.

### Catalogs and readiness

A private catalog describes declared environments; it is not a connection or
execution grant. [The synthetic catalog](../tests/fixtures/work-classification/catalog.json)
shows source references and capability evidence. `list --catalog FILE` observes
local records without starting runtimes. `check --catalog FILE` validates their
schema and references. Optional `--probe` makes bounded WSL/SSH observations;
missing access remains unverified, not an unavailable capability.

Sources declare readable paths per observer, selected by
`ENVIRONMENT_INVENTORY_HOST` (or saved `--inventory-host`). They can reference
placement TSV or explicit scalar JSON Pointers; a remote source may deliberately
have no readable path here. SSH probes need explicitly configured identity,
known-hosts and connection details; executable SSH config directives are refused.
A WSL connection can reference a declared distro field; an SSH connection's
optional `wslDistro` identifies only its outer container. None of these records
substitutes for the inner runtime principal or config root. Exact schema and
validation live in [environment_inventory.py](../bin/environment_inventory.py).

A declaration's `INVENTORY` table binds `site`, `catalog`, and `environment`.
Run `check --declaration PLACEMENT.md --site SITE --readiness` after changing the
CLI, placement, connection or declaration. Readiness covers every registered
CLI in that environment; it is broader than normal start and cannot be narrowed
to one workspace. It neither changes state nor proves successful agent work.

For versioned declarations, add a reviewed CLI descriptor and locations, then
run `inventory declare-agent` in the registered topic tracking the declaration
and catalog. It registers that CLI as pending; it does not install it. Save and
integrate the declaration through normal Git work before runtime adoption.
On the selected runtime use its existing saved inputs:

```console
python bin/place.py inventory adopt --environment ENVIRONMENT --source-ref REVISION
```

`--check-inputs` checks source prerequisites only. Adoption applies the committed
catalog, checks readiness and Grok discovery, then records active in the untracked
saved config. Failure stays pending; repeat the same operation after resolving
the cause. The catalog revision and retained runtime HEAD are distinct, and an
external runtime declaration is not a catalog Git blob. A bootstrap must consume
these same saved inputs; an explicit-declaration launch cannot infer adoption.
Unrelated source commits do not invalidate unchanged adopted inputs.

Legacy `inventory prepare-agent` / `activate` still support catalog-mutating
consumers: prepare while pending, perform authorized installation/login through
the existing maintenance route, then activate and test the ordinary start path.
Neither workflow changes trust or grants transport/root authority. Catalog IDs
must identify real runtimes rather than unrelated clones. Resume interrupted
catalog work in its owning environment; do not remove shared claims or edit
operational JSON to bypass a refusal.

For Grok, use the installed `grok inspect --json` in affected workspaces to
verify trust and project instruction discovery. Visible skills do not prove
standing instructions were loaded. Git-ignore diagnostics explain missing
requested paths but do not override discovery or change ignore policy. Grok's
compatibility discovery can expose duplicate owners; placement itself does not
enable native worktree creation or automatic approvals. OpenCode uses its native
`.opencode/skills` layout; file checks likewise do not prove a session read it.

### Standard command names on POSIX

An owner can use `entry install --config FILE --directory DIRECTORY --tool TOOL`
to put managed names in a dedicated PATH directory before vendor binaries. This
connects ordinary `codex`, `claude`, or other declared commands to the same start
checks. Do not replace vendor binaries or unrelated aliases. Keep the dispatcher
source installed; repeat install to rebind a moved vendor/source or add tools.
Use `entry remove --directory DIRECTORY`, then remove that PATH entry, to remove
owned names while preserving vendors and settings. Windows transport stays with
the environment's existing SSH lifecycle.

Normal starts choose the deepest declared workspace, enforce an explicit child
binding, and preserve native streams, terminal, signals and continuation arguments.
They check the effective launch directory, not subsequent tool confinement.
They do not adopt, establish trust, check releases or probe models. Exact native
maintenance/help/version operations remain reachable with broken saved placement;
there is no general skip-check option. [managed_entry.py](../bin/managed_entry.py)
owns the permitted maintenance forms and vendor resolution.

## Route work without executing it

`python bin/place.py classify --help` accepts a catalog and a work document.
Use the existing [work fixture](../tests/fixtures/work-classification/work.json)
and catalog as a runnable example. Work phases identify purpose, required
capabilities, executor readiness and constraints; excluded records retain their
reason. Results keep technical eligibility separate from readiness, and expose
unknown evidence rather than inventing a preparation route.

A preferred environment affects ranking, not permission. Declare approval and
sandbox mode, interoperability, acceptance risk and material prohibitions as
capability requirements when they affect routing. An OS label alone cannot prove
those conditions. Classification does not launch, install or connect. Use the
[classify-work skill](../skills/classify-work/SKILL.md) for the judgment and
preserve the same constraints in any receiving agent's request.

## Inspect an agent's reported configuration

With trusted, already installed/authenticated CLIs, run:

```console
python bin/agent_report.py --output report.html
```

The standalone file can also be copied independently. It starts **new diagnostic
sessions**, collects metadata and writes a new offline HTML report. Use `--help`
for platform selection, target directory, timeout and trusted plugin locations.
It never automatically retries or overwrites a report. It distinguishes
reported `loaded`/`available` state from local path existence; unknowns and
uncheckable paths are not successful inventory observations.

These restricted sessions are not ordinary interactive sessions. Native startup
may still invoke trusted hooks/plugins, refresh authentication, write caches or
incur model charges. No tool permission is broadened, but the collector cannot
sandbox a custom launcher or startup hook. Raw model output and configuration
bodies are excluded; metadata and filenames may still be private. Review HTML
before sharing and keep real-environment reports outside this public repository.
Failure stage/code describes one query without exposing its payload or retrying.

For an existing launch entry, `--launch-config FILE` maps platform IDs to literal
argv prefixes. Use absolute executable/path arguments, preserve the selected
product's target cwd and output/status, and keep credentials out of argv. A
`place.py start` prefix needs the declared target workspace, its private source
inputs and trailing `--`. Windows batch shims are refused; use the native binary
or existing `node.exe` plus CLI JavaScript path. The report cannot attest the
internals of a custom launcher.

### Add a report adapter

Report plugins are separate from vendor agent plugins. Explicit `--plugin-dir`
locations contain trusted Python modules executed as the current user; there is
no automatic discovery or dependency installation. An API v1 module exports
`PLUGIN_API_VERSION = 1` and `get_platforms()` returning adapter objects. Each
object supplies a unique ID, display name, PATH candidates and restrictions,
plus methods to construct version/query arguments and parse their responses.
The built-ins in [agent_report.py](../bin/agent_report.py) are working examples;
`load_platforms` and `validate_data` own the exact interface and schema.

For adapter authors, the interface consists of:

| Member | Purpose |
| --- | --- |
| `id`, `name`, `cli_candidates`, `restrictions` | Unique platform ID, display label, ordered PATH command names, and diagnostic limitations |
| `version_args()` | Return literal arguments for a version query |
| `parse_version(stdout)` | Return a version token, not arbitrary output |
| `query_args(target)` | Return literal arguments for a fresh metadata query in the target directory |
| `parse_response(stdout)` | Extract final metadata and reject failed/incomplete product responses |

The result has `files`, `skills`, and `unknowns` lists. Items use a required
nonempty `name` and optional string `path`, `source`, `role`, `scope`, and `state`.
For a skill, distinguish its body reported `loaded` from merely `available`;
use `unknown` when that cannot be established. A non-file origin belongs in
`source`, not an invented local path. Omitted categories become unknowns.

Argument construction must be side-effect-free; only the collector launches
CLIs. Query a fresh read-only session and return final normalized metadata in
`files`, `skills`, and `unknowns`, not raw stdout or exception text. Document the
adapter's dependencies, authentication and restrictions. Malformed adapters fail
before collection; response errors remain isolated to their platform.
[CI evidence](ci.md#agent-report-observation) records the limited live validation.

## Registered Git work

Branch management links a work request to a topic and worktree, enforces normal
integration and retains evidence of refused or interrupted operations. It requires
Python 3.10+, Git 2.31+ for hook installation, and Git for Windows' shell on
Windows. Merge-result preparation additionally needs the Git `merge-tree`
capabilities checked by the command. Keep its reviewed source and Python runtime
available for installed hooks.

Use `python bin/place.py branch --help` for the operation index and each operation's
help for arguments. Install with `branch install --repo REPO --remote REMOTE`;
it preserves compatible existing hooks and refuses unknown collisions. Reinstall
from a reviewed checkout to rebind source/runtime or repair packing settings.
Before updating the source that supplies its own hooks, rebind from a separate
reviewed source. A changed dispatcher needs reviewed migration, not overwriting.

Choose work by its request, not branch age or name:

| Need | Existing operation |
| --- | --- |
| Start independent work from the fetched remote default | `branch begin --mode new` |
| Start work depending on an unfinished task | Add `--depends-on` to new work |
| Register existing integration/topic history | `branch begin --mode adopt`, with its reviewed historical `--base` and integration destination |
| Adopt a fetched remote-only branch into an absent path | Add `--from-remote` to adopt; continuation keeps the original registered tip |
| Resume the same unfinished task | `branch begin --mode continue` |
| Import an update of that same remote branch | Continue with `--sync`, then `git merge --ff-only REMOTE/BRANCH` |
| Diagnose a refusal or interruption without changing state | `branch check --repo REPO --json` |
| Remove an integrated worktree/registration, retaining history | `branch retire --repo REPO --task TASK` |

Each worktree has one lead for Git updates. Fetch before starting independent
work; new worktrees use absolute paths. The default branch is an integration
destination, not a direct-development branch. Register it with itself as its
destination when adopting an existing checkout. Another clone must register the
same request against its own remote history; operation permissions are not portable.

To integrate, run `branch prepare-merge --repo DESTINATION --task SOURCE_TASK`,
then in that destination run `git merge --no-ff --no-commit SOURCE_BRANCH`.
Verify the combined tree before committing. Parent work must be integrated first,
unless the child integrates directly into that parent. Changed tips require fresh
preparation; an outstanding operation must be resolved before replacing its baseline.

Fresh operations require clean staged/unstaged/untracked state and refuse ignored
collisions. After failure, inspect the existing operation with `branch check`;
its outcome and next action preserve what is known, not an invented Git exit
status. Retry through the same entry after resolving the reported cause. No
automatic reset, stash, clean, abort or source replacement repairs the operation.
Only genuine conflict paths permit resolution edits; unrelated edits in an incoming
file cannot borrow the merge's authorization. Unsupported filters, submodules,
merge drivers and worktree conversions need separate handling.

Retire only through `branch retire`; ignored files also prevent removal because
they may contain another working tree. Legacy/adopted registrations and native
locks protecting source/runtime dependencies can require separate maintenance.
Do not unlock dependencies or alter registry files to force retirement. Branches
and commits remain; retirement is not branch deletion or abandonment.

### Pushes and explicitly approved exceptions

After committing, use the environment's canonical
`python bin/push_preflight.py REPO`, passing its configured private `--policy`.
The read-only command returns a decision, not a push side effect. Inspect
`decision`, not exit zero; execute returned `push_argv` only for `push`. Resolve
missing facts for `ask`, and retain the reason for `hold`. `--help` describes
intent/temporary/OSS inputs; [push_preflight.py](../bin/push_preflight.py) owns
policy ordering and destination selection.

Default-branch automatic push grants belong in the owner's policy, using
repository URLs or explicitly authorized private/OSS categories. Exclusions
outweigh those grants. A public repository is not automatically OSS, and a WIP
subject is not a temporary-save instruction. Never omit an unreadable policy or
change remote, force-push or remove hooks to evade refusal.

For a user-approved cherry-pick, register the exact source, destination and
approval through `branch allow-cherry-pick`. Each source in a sequence needs its
own permission; prior successful picks survive a later rejection. For explicitly
requested tags, create the tag, register `branch allow-tag-push` with its full
commit and approval reference, then push that exact tag to the registered remote.
Permission is consumed before transport; failed transport or dry-run needs fresh
registration under still-valid approval. Neither operation authorizes rewriting
history, replacing/deleting remote tags, or publishing a release without approval.

The guards prevent accidental misuse, not deliberate configuration tampering.
Missing hooks are detected by the remaining checks, not magically executed.
Git cannot distinguish pruning packed loose refs from deleting a branch, so the
installation disables automatic reference packing. `git pack-refs --all --no-prune`
is supported; repair changed packing settings by reinstalling the reviewed source.
Existing native dependency locks are preserved across source rebinds. See
[CI coverage](ci.md) for behavioral proof and its limits.

## Share current state across environments

The maintainer's [handoff rule](../rules/handoff.rule.md) keeps local resumption
in the nearest HANDOFF.md and cross-environment work in an explicitly selected,
accessible shared task. [human-handoff](../skills/human-handoff/SKILL.md) governs
human relays; classification does not authorize execution. Saving a task is not
recipient receipt or acceptance. The [handoff fixtures](../tests/fixtures/handoff/README.md)
test this distinction; real host delivery and UI copying need separate evidence.

For an existing pair that should receive the same current-state fragment, a
locally reviewed `rules/handoff-receive.json` binds one HTTPS repository, branch,
document and historical revision. Its fields are `version: 1`, `pair`,
`repository`, `branch`, `document`, and `initial_revision`; the target is always
that workspace's HANDOFF.md. Keep private bindings/fragments outside this repo.
Received Markdown cannot select paths or execute commands.

Configured `start` receives after placement checks and before launch, including
resume. Existing GUI owners can call `handoff-receive --workspace PATH` at that
same point; a standalone call does not prove GUI integration. Updates arrive on
the next start/resume, not in a running session. Senders update the fragment
through normal registered Git integration and push; detailed results stay in the
shared task, and receipt blocks are not republished as source.

Conflicts and failed fetches stop dependent starts. For work independent of that
state, `start --handoff-independent` retains an explicit unconfirmed warning.
Local content outside the receipt block and Git working state are preserved.
Replacement failures retain private recovery data and a journal in Git metadata;
retry the same entry and follow its recovery-path diagnostics without discarding
competing edits. A success marker does not erase unresolved recovery state.
Byte receipt cannot attest a model's understanding or force an open editor to reload.
