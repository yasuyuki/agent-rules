---
name: maintain-environment-inventory
description: 環境の新規構築・変更・移行・廃止、agent CLI の導入・削除・読込設定変更、または利用環境の選択時に、環境一覧と全 agent の管理 skill 配置を整合させる。通常の製品コード編集や単なる test 実行には使わない。
---

# Maintain environment inventory

Use the catalog and public `place.py` path explicitly supplied by the environment
binding. Do not search HOME or other controller copies to select an authority.
If either setting is missing, resolve it from the environment's placement
instructions before modifying an inventory.

## Select an environment

Read `place.py list --catalog <catalog> --purpose <purpose> --json`. Keep the
requested purpose: zero matches does not authorize a normal-development fallback.
An explicit request to repurpose a named environment is an environment change,
not a selection fallback. Preserve its other purposes unless their removal is
requested or necessary to satisfy the requested isolation constraints.
Multiple candidates require a choice grounded in the request. `active` is an
ordinary candidate; `pending` is for construction or repair; `retained` needs an
explicit user selection; `retired` and `unclassified` are not candidates.
Unverified reachability requires checking and does not mean absent. A stopped
environment may still be a candidate. `--probe` observes; it must not start a
distro/service, authenticate, apply placement, or change permissions.

Use the selected environment's existing start/setup/apparatus entry point within
its authorization boundary. Catalog membership grants no execution permission.

## Change an environment

Inventory updates are required for creation, cloning, restoration, migration,
deletion, purpose/state changes, connection or runtime principal changes,
HOME/workspace/entry-point/source-reference changes, and agent addition, removal,
or placement changes. Runtime state alone needs no edit. A version update needs
checking only unless placement or supported capabilities change.

Before construction, identify the affected environment ID and transition it to
`pending`. Update authoritative declarations for facts derived from those
declarations; update catalog references/classification instead of duplicating
host, user, HOME, workspace, executor, or runsRoot values. Keep outer transport
and inner runtime principal distinct. Preserve unknown or retained environments
as explicit rows instead of dropping them.

For a versioned catalog and a runtime using saved launch inputs, review the CLI's
descriptor and locations, then use `place.py inventory declare-agent --declaration
<D> --site <S> --tool <CLI>` in the registered source topic. Commit/integrate/push
the declaration through the existing branch workflow before runtime adoption.
Use `place.py inventory adopt --config <existing-start-config> --site <S>` on the
target runtime. It applies the site, checks all registered CLI readiness and Grok
discovery, and records pending/active only in that existing untracked start config.
Do not copy runtime JSON back to another clone or add a receipt registry. A retained
runtime may select the exact committed catalog with `--source-ref <revision>`;
this does not attribute unrelated dirt or an external policy to that commit.
The host's bootstrap must consume the same saved inputs before adopting this path.
Catalog listing reports the declaration state, not a remote runtime's adoption.

For legacy consumers not yet using that path, review locations first and run
`place.py inventory prepare-agent --declaration <D>
--site <S> --tool <CLI>` on the target runtime, with its existing rule/skill inputs.
The operation resolves the catalog and principal from the site's INVENTORY binding,
registers the CLI and writes pending together. Do not assemble operational JSON
references or state transitions by hand. A conflicting existing registration is
refused, not replaced. Resume through the same operation after correcting its
reported prerequisite; exact registration is a no-op.

Include all installed agents in the runtime, including the constructing agent
and previously installed CLIs. Compare the supported tool/subject descriptors
against the runtime PATH and declared installation locations. Placement `absent`
describes rule delivery, not whether a CLI is installed. Register new CLI kinds
with a descriptor as part of installation. Do not claim discovery of arbitrary
unknown binaries across the filesystem.

Distribute this skill and its conditional reading binding to every registered
agent through the existing `place.py apply/check` mechanism. Use native skill
discovery where supported; otherwise reference the installed SKILL.md from the
agent's always-read configuration. An agent supporting neither remains an
incomplete installation. Do not overwrite unmanaged skill directories.

Check the affected site's binding with `place.py check --declaration <D> --site
<S> --readiness`. This read-only check resolves the catalog and environment
only from that site's `INVENTORY` row. It checks every registered CLI's declared
principal, config root, placement sites, required management skill and binding,
managed bytes, and visible supported CLIs that are not registered. Do not pair
`--readiness` with a workspace or scope restriction. Use ordinary `check` for
partial placement work.

For the saved-input path, resume `inventory adopt` with the same config/site/ref.
It never changes trust automatically; fix only the explicitly authorized folder
using the CLI's official operation when inspection reports it missing.
For legacy consumers, run `place.py inventory activate --declaration <D> --site <S>` with
the same inputs. It rechecks full readiness and refuses changed inputs before
saving active; failure leaves pending. Do not edit state to bypass that check.
Only mark construction `active` after repair and readiness pass. `active` means
the machine is ready to launch; it does not claim that an agent has followed a
skill or completed a behavioral acceptance. Perform that acceptance through the
ordinary entry point after activation. Partial failure stays `pending` with a resumable handoff;
do not remove it or restore `active` as cleanup. Intentional retained/retired
transitions keep their intended state. Repair uses existing setup/maintenance
entry points, with the constructing agent's skill/binding present; do not add a
generic normal-start bypass. Limit checks to the affected environment so an
unrelated remote outage does not block local work.

## Experiment boundary

Keep the skill/binding fixed as common preparation for both arms, separately
from variants. Temporary arms inside a registered experiment are not new
inventory environments. Subjects may leave sanitized change proposals in
evidence, but cannot edit shared inventory or baseline. During comparison the
controller does not change the shared catalog. Actual environment changes belong
to the environment maintainer outside the cycle. Preserve executor boundaries.

Report machine readiness separately from observed session behavior. Managed-entry
preflights do not enforce direct CLI invocations or all model behavior after a
skill has been read.
