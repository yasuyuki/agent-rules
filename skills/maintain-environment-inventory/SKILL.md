---
name: maintain-environment-inventory
description: 環境の新規構築・変更・移行・廃止、agent CLI の導入・削除・読込設定変更、または利用環境の選択時に、環境一覧と全 agent の管理 skill 配置を整合させる。通常の製品コード編集や単なる test 実行には使わない。
---

# Maintain environment inventory

Use the catalog and public `place.py` path supplied by the environment binding;
do not find an authority through `HOME` or another controller. Resolve a missing
binding from its placement instructions before changing inventory.

## Select an environment

Use `place.py list --catalog <catalog> --purpose <purpose> --json` and preserve
the requested purpose: no match does not authorize a normal-development fallback.
Purpose and lifecycle establish eligibility only. Before selection, use
`classify-work` and read-only `place.py classify` to compare the requested
approval/sandbox boundary, interoperability, acceptance risk, and prohibitions
against capability evidence. OS/distro names and active state do not establish
those facts; unknown remains unknown and cannot justify selection or a
contract-changing preparation.

Repurposing a named environment is a change, not a fallback. Preserve its other
purposes unless their removal is requested or necessary for the requested isolation.
Choose among
candidates from the request: `pending` is construction/repair, `retained`
needs explicit user selection, and `retired`/`unclassified` are ineligible.
Unverified reachability needs observation, not an absence finding; `--probe`
must not start services, authenticate, apply placement, or change permissions.
Catalog membership never grants execution permission: use the selected
environment's existing authorized entry point.

## Change an environment

Update inventory for environment creation, restoration, migration, deletion,
purpose/state, connection/principal, workspace/entry-point/source-reference, or
agent/placement changes. Runtime state alone needs no edit; a version change only
needs checking unless it changes placement or supported capability. Identify the
environment and make construction `pending`; retain unknown/retained rows and
derive host, user, home, workspace, executor, and run-root facts from their
authoritative sources. Keep outer transport distinct from the runtime principal.

For saved launch inputs, declare an added CLI in the registered source topic with
`place.py inventory declare-agent`, then use the existing branch workflow before
the target runtime adopts its committed source via `inventory adopt`. Use
`--config` only for a nondefault saved config and `--check-inputs` only to
validate inputs before interruption. For legacy consumers, use
`inventory prepare-agent` on the target; it resolves the site's inventory
binding and creates pending state. Follow each command's help for arguments and
its reported recovery path; do not hand-assemble runtime state, replace a
conflicting registration, copy runtime JSON between clones, or add a receipt
registry.

Register every installed supported CLI, including the constructing agent, from
declared descriptors and installation locations; placement `absent` does not
mean its CLI is absent. Deliver this skill and its conditional binding to every
registered agent through `place.py apply/check`. Use native discovery where it
exists, otherwise the managed always-read reference; an agent with neither is
incomplete. Never overwrite unmanaged skill directories.

Run full affected-site readiness with
`place.py check --declaration <D> --site <S> --readiness`; use ordinary
`check` for partial placement. Readiness resolves the site's binding and checks
the registered environment contract; it is not session-behavior acceptance. On
saved-input runtimes, resume `inventory adopt`; on legacy ones, use
`inventory activate`. Both retain pending state on failure. Do not edit state
to bypass readiness or change trust automatically. Mark active only after repair
and readiness; perform behavioral acceptance through the ordinary entry point,
and leave partial failures pending with a resumable handoff.

## Experiment boundary

Keep the skill/binding common to experiment arms; temporary arms are not inventory
environments. Subjects may propose sanitized changes in evidence but do not edit
shared inventory or baseline. The controller does not change the shared catalog
during comparison; actual environment changes belong to its maintainer. Managed
preflights do not prove direct CLI use or later model behavior.
