# User manual

Use the [README](../README.md) to install from source. The project CLI manages
your own sources. The advanced checkout commands below additionally support the
maintainer's catalog and explicitly supplied environment declarations; they do
not enroll an ordinary project in that environment policy.

## Project rules and skills

Use Python 3.10+ and the pinned Rulesync 16.39.1 executable installed by
`npm ci --ignore-scripts` from this checkout. The Python wheel only includes the
project entry and staging adapter; runtime, Git hooks, catalogs and optional
review tooling are checkout-only until their separate extraction is complete.

Create a project-local `sources/rules/policy.md` with native Rulesync frontmatter:

```markdown
---
root: false
targets: [codexcli, claudecode]
---
Follow this project's documented conventions.
```

Create `rulesync-placement.json` alongside `sources/`:

```json
{
  "version": 1,
  "input_roots": ["sources"],
  "targets": ["codexcli", "claudecode", "grokcli"],
  "features": ["rules", "skills"],
  "output_root": ".",
  "global": false
}
```

Paths are relative to that configuration. A source root directly contains
`rules/` and/or `skills/`. Select every source explicitly; no parent lookup or
maintainer catalog is injected. Generic skills can be selected by pointing an
input root at a separately obtained agent-skills checkout. A skill directory
contains native `SKILL.md` plus its relative supporting files.

```console
agent-rules apply --config rulesync-placement.json
agent-rules check --config rulesync-placement.json
```

Pass `--rulesync` to select an installed executable outside PATH. It must report
16.39.1; applying never downloads software. For user scope, use a separate config
with `global: true` and an explicit disposable HOME as `output_root` during
verification. Do not repeat the same policy in both user and project inputs.
Only rules and skills are managed; permissions, hooks, MCP and ignores are not.

Rulesync generates each target in an isolated staging directory. Shared output
paths must have identical contents across targets; conflicting `AGENTS.md`
content is rejected rather than resolved by target order. Use identical shared
policy for Codex and Grok, with Claude-specific fragments separately targeted.
For the three-target example, only Codex generates shared `AGENTS.md`; Grok
reads it and generates its own skills. Claude uses `.claude/rules/`. A root
`CLAUDE.md` would also be read by Grok and duplicate common policy, so do not
select that shape for this collocated consumer set. Grok also discovers
`.claude/rules/` by default. Its machine configuration owner must explicitly
set native `compat.claude.rules = false` for this arrangement; the adapter does
not manage that settings file. Native `inspect` lists disabled entries too, so
check enabled instruction paths and the compatibility cell. Filename order controls composition. Duplicate relative rules and same-name
skills across roots are rejected, rather than silently overlaying one owner.

The adapter owns only paths recorded by its successful apply. Unknown files,
unknown same-name skill directories and symlinks/junctions are conflicts.
Changes made directly to owned outputs are preserved by refusing replacement;
move an intentional handwritten edit into its source before applying again.
Delete a source and apply to remove its previously owned output. Empty sources
remove owned output; unrelated files remain. A repeated apply preserves unchanged
files. Check stages expected output outside the destination and reports drift. A check
racing an apply may report an in-progress transaction; it never repairs or writes.
Apply serializes writers and recovers an interrupted transaction only if files
still match its recorded before/after bytes, preserving later user edits.

Existing handwritten instructions must be explicitly preserved as source before
ownership transfer. Neither matching filenames nor matching bytes authorize
adoption. Do not run old and new installers on the same output root. The live
migration owner must retain the old revision, source inputs and outputs for
recovery; reverting must stop at any subsequent user edit, rather than overwrite
it. Synthetic generation proves files and safety behavior, not model loading.

### One-time handwritten-output handover

After the old public writer has stopped and each handwritten instruction has been
preserved in a Rulesync source, an operator may transfer one reviewed destination
with an explicit before-state plan using agent-rules handover --config rulesync-placement.json --plan reviewed-handover.json.

The plan is not an ownership manifest and never infers ownership from equal bytes
or legacy markers. It contains exactly version (1), output_root, files, evidence, backup_root,
and desired_sha256. desired_sha256 is the lowercase SHA-256 of the reviewed generated
ownership manifest. output_root must resolve exactly to the configured output. Each
files entry has an allowed Rulesync path, its current lowercase SHA-256 sha256, and
current numeric mode; list every reviewed existing allowed path to replace or
remove. An old CLAUDE.md may be listed for reviewed removal when Grok will own
AGENTS.md. Metadata, hooks and arbitrary paths are rejected.

backup_root must be new, absolute, plain, and outside all selected source and
output roots. Before mutation, handover writes the reviewed before bytes and modes,
the plan, configuration and generated desired ownership manifest there. It refuses
an existing ownership manifest, pending transaction, changed reviewed file,
symlink, unknown replacement, same-name skill conflict or reused backup. The
backup remains for a deliberate rollback procedure; handover does not adopt
unchanged bytes or replay it automatically. A successful handover publishes normal
ownership, so future apply and check use their usual protections.

## Declared placement and source authoring

The following declaration commands are a temporary compatibility surface for
pre-transition runtime consumers; they are excluded from the Python package.
Their removal depends on those consumers adopting the Rulesync source contract.
Do not use them as a second writer of Rulesync-managed outputs.

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

To consume selected canonical `.rule.md` policies with the new backend, export
explicit inputs to a new disposable source tree:

```console
python bin/rules.py rules --dest exported --targets codexcli claudecode grokcli
```

Point `input_roots` at the exported tree. Export is an input conversion, not an
installer: it neither writes consumer paths nor replaces Rulesync formatting.
Edit only the original policies, regenerate a fresh export, and never maintain
an exported copy as a second source. Tool bindings sharing `AGENTS.md` are
combined to preserve the existing shared-file policy. Use `--exclude-id` for
explicit location exclusions before generating a separate scope. Add `--global`
when exporting user-scope inputs, where Codex and Grok use separate native roots.
Use `--skills skills` to include this checkout's project skills in the same
disposable source tree; do not select this repository root as native input,
because its canonical rules use the legacy authoring format. Native private/project
rules need no conversion. Old standalone `render`/`verify` have been removed.

### Original and third-party skills

[agent-skills](https://github.com/yasuyuki/agent-skills) owns the generic
human-handoff, optimize-human-docs and optimize-agent-docs sources. This checkout
owns only its project-specific inventory/classification/verifier skills.
No mirror or inverse synchronization exists. Old pinned consumers retain their
old bytes until separately adopted; that is not a second editing workflow.

Third-party grilling and create-verification-skill copies were removed. Their
recorded upstream references and license provenance remain in
[UPSTREAM.tsv](../skills/UPSTREAM.tsv); consumers select upstream sources explicitly.
The [project verifier](../skills/verify-agent-rules/SKILL.md) retains the legacy
placement/composition proof until those runtime consumers migrate; it is not
proof of the new backend. Use the backend tests in the CI guide for that scope.

## Launch and environment maintenance

Normal launch is owned by the independently installable
[agent-runtime package](../packages/agent-runtime/README.md). Its explicit adopted
configuration selects vendor executables, workspace scope and fixed HANDOFF and
workspace-lifecycle interfaces. Launch does not generate placement, scan inventory,
adopt configuration or query vendor releases.

The checkout's `start` and `standard-start` process entries delegate to that package
before loading placement or inventory. `standard-start --config FILE TOOL -- ...`
uses runtime configuration; `start --config FILE WORKSPACE TOOL -- ...` selects an
explicit runtime workspace `id`. Legacy `placement-start.json` is not converted or
silently accepted. `save-start-config` remains an adoption-input operation for
pinned consumers, not a producer of new runtime configuration.

Unmigrated live consumers must retain their pinned source and saved configuration
until the separate adoption task verifies the new package, configuration, entry
and rollback source together. Installing or testing this source does not switch
a live PATH, trusted bundle, hook or lifecycle state.

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

### Standard command names

The runtime wheel provides `codex`, `claude` and `grok` in its isolated installation
directory, separate from vendor executables. Its guide defines configuration and
native argument handling for Linux and Windows. The old POSIX `entry` ownership
operations remain available for existing links; the dispatcher now delegates to
the runtime process boundary. Do not replace a live pinned dispatcher until its
configuration has been adopted. Vendor files and global PATH are not changed by
package installation into an isolated environment.

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
`agent-runtime` prefix needs an explicitly adopted runtime configuration, tool
name and trailing `--`. Windows batch shims are refused; use the native binary
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

## Workspace lifecycle

The independent [workspace lifecycle guide](../packages/workspace-lifecycle/README.md)
documents the current task and worktree contract. It owns only state Git cannot
recover: task identity, dependencies, acceptance, holds, retirement requests and
process-use leases. Git remains the source of truth for worktree, branch, HEAD,
upstream, lock, merge and removal operations.

The package is version `0.1.0` and is not published to PyPI. Installing it from
its subdirectory does not adopt existing consumers, migrate a registry, rebind
hooks, or deploy a live environment. Pinned legacy consumers remain on their
existing interface until an explicit migration proves the boundary. A legacy
registry is rejected rather than auto-migrated.

## Share current state across environments

The maintainer's [handoff rule](../rules/handoff.rule.md) keeps local resumption
in the nearest HANDOFF.md and cross-environment work in an explicitly selected,
accessible shared task. [human-handoff](https://github.com/yasuyuki/agent-skills/blob/main/skills/human-handoff/SKILL.md) governs
human relays; classification does not authorize execution. Saving a task is not
recipient receipt or acceptance. The [handoff fixtures](../tests/fixtures/handoff/README.md)
test this distinction; real host delivery and UI copying need separate evidence.

For an existing pair that should receive the same current-state fragment, a
locally reviewed `rules/handoff-receive.json` binds one HTTPS repository, branch,
document and historical revision. Its fields are `version: 1`, `pair`,
`repository`, `branch`, `document`, and `initial_revision`; the target is always
that workspace's HANDOFF.md. Keep private bindings/fragments outside this repo.
Received Markdown cannot select paths or execute commands.

Configured runtime receives before launch, including resume. The fixed receiver
CLI is `python bin/handoff_receive.py --workspace PATH`; its JSON status and exit
code identify success or refusal. Existing GUI owners retain their receiver entry;
adopt exactly one receiver owner for each launch path. A standalone call does not prove GUI integration. Updates arrive on
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
