---
name: verify-placement-routing
description: Model-check with TLA+ that the work-routing rule starts a change in an environment that can place it in every environment it must update, and that source is edited only on ubuntu-26-development. Use when a change touches the routing rule in work-records (README "開発を行う場所", the windows-controller workspace rule), environment selection in maintain-environment-inventory, the placement routes in agent-environment pstack/environments.json, or the delegate route in pstack/sync.py.
license: MIT
---

# Verify placement routing

A skill or rule update often has to be placed in several environments of the
catalog (`rules/environments.json` in work-records): windows-controller,
ubuntu-operator and ubuntu-26-development. Every recorded placement route
starts on windows-controller, and ubuntu-26-development reaches only itself
and GitHub (work-records #258). A rule that picks the starting environment by
repository kind sends multi-environment work to ubuntu-26-development, which
pushes the source and then cannot place it anywhere else (work-records #265).
This check explores every non-empty set of target environments and every
order of edit, integration and placement.

## Promises

| Invariant | Promise | Harm when broken |
| --- | --- | --- |
| `PlacementNeverStalls` | After the source is integrated, the session can still place it in some target it has not placed yet. | The session ends with a target unplaced, and the owner must notice and relay the rest. |
| `SourceEditedOnDevelopment` | Source is edited only on ubuntu-26-development. | Management repositories are edited and built on the controller, against #258. |

TLC's deadlock check adds the third promise: every run reaches "placed in
every target". `TypeOK` guards the model itself.

## Coverage

| Model | Source |
| --- | --- |
| `Start` with `Rule = "by-target"` | work-records README "開発を行う場所" and `rules/rulesync/windows-controller/rules/workspace.md` |
| `Start` with `Rule = "by-repo-kind"` | the same two texts before #265 ("管理系repo ... は通常Linuxのsession") |
| `Reach` | agent-environment `pstack/environments.json`: windows-controller has the empty (local) transport, the other two `ssh.exe` and `wsl.exe`. No environment other than windows-controller has a route |
| `Delegate` | agent-environment `pstack/sync.py` `delegate`, `DELEGATE_ENV = 'ubuntu-26-development'` |
| `EditHere` | the ubuntu-26-development session edits a registered task checkout |
| `Integrate` | lifecycle `finish` pushes to GitHub, which every environment reaches |
| `Apply(e)` | Rulesync apply, check and reapply through the route in `e`'s rulesync README |
| selection | agent-rules `skills/maintain-environment-inventory` "Select an environment" |

`check.py --routes` compares `Reach` with the live route table, so a new
route or environment fails the run until the model is updated.

Last confirmed against work-records `6c01142b4fdd010c19fa7699175011fd888ef393`, agent-rules
`ae8ab0ad45fa14a5c1fed0e42629ecdebc1ee549` and agent-environment `5da2541`. Move a commit forward
only after you have read every change to the covered text and code since it
and confirmed that the table and the model still describe it.

## Does a change touch it?

```sh
git -C <work-records> diff 6c01142b4fdd010c19fa7699175011fd888ef393 -- README.md rules/rulesync/windows-controller/rules/workspace.md
git -C <agent-rules> diff ae8ab0ad45fa14a5c1fed0e42629ecdebc1ee549 -- skills/maintain-environment-inventory
git -C <agent-environment> diff 5da2541 -- pstack/environments.json pstack/sync.py
```

In the README only the section "開発を行う場所" counts. In `sync.py` only
`delegate` and `DELEGATE_ENV` count. In `environments.json` only the set of
environments and each `transport` count.

## Run

Requires Python 3.12 or later, Java 11 or later, and `tla2tools.jar` 1.7.4 from
<https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4>. The script refuses any
other jar by SHA-256. From the agent-rules checkout:

```sh
python3 -B skills/verify-placement-routing/scripts/check.py --tla2tools /path/to/tla2tools.jar --java /path/to/java --routes <agent-environment>/pstack/environments.json
```

`--tla2tools` and `--java` default to `$TLA2TOOLS` and `$JAVA`. Pass `--out`
with a new directory to keep the raw TLC output. Exit 0 means every row
matched its expectation, exit 1 a mismatch, exit 2 a missing or wrong jar. A
run takes a few seconds.

| Rule | Checked | Expected |
| --- | --- | --- |
| `by-target` | `PlacementNeverStalls`, `SourceEditedOnDevelopment`, deadlock | pass |
| `by-repo-kind` | `PlacementNeverStalls` | violated |
| `controller-edits` | `SourceEditedOnDevelopment` | violated |

`by-repo-kind` is the rule before #265. `controller-edits` lets the controller
edit its own checkout instead of delegating. Both rows prove that their
promise can fail.

## Read a result

Use the `statechart` skill on `PlacementRouting.tla` with
`PlacementRouting.map.mjs` as the view and a config that sets `Rule` and the
two invariants. The raw trace of a run is in `<out>/<rule>-<invariant>/tlc.out`.

A violation is a real routing bug when its path is something a session can
do under the current texts: for example, the README sends a change with
targets `{windows-controller}` to ubuntu-26-development, and after
`finish` nothing it can run places it. Confirm it by reading the current
section and the route table. A path the texts and routes cannot produce, or a
`TypeOK` violation, is a modeling error: fix the model and keep both broken
rows failing.

Never weaken an invariant, add a precondition, or drop a target set to make a
row pass. Report a real bug in work-records' Issues with its path in the
words of the routing rule. When it is reported but not yet fixed, add it to
`FINDINGS` in `scripts/check.py`.

## Update for an intended change

When the routing rule changes, change `Start` so that it states the new rule,
and keep the old rule as a broken row if it is still a plausible mistake. When
a route is added or removed in `pstack/environments.json`, change `Reach` and
`MODEL_ENVS` in `scripts/check.py`. Run the script, then advance the commits in
**Coverage**.

## Scope

A pass covers the three environments, every non-empty set of targets, and one
change from start to placement. It assumes that GitHub is reachable from every
environment, that a delegated agent finishes its source work, and that apply
succeeds when its route runs. It does not cover authentication, CLI
acceptance, a failed apply, two changes at once, or the retained and legacy
environments of the catalog.
