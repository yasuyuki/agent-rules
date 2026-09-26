# Development, verification and CI

Use an active Python environment in the checkout root. To build the sdist and
wheel and validate their metadata:

```console
python -m pip install build twine
python -m build
python -m twine check --strict dist/*
```

The build makes the wheel from the sdist. The main distribution includes only
the project entry, Rulesync staging adapter and pinned dependency lock. Runtime
build and test ownership is in [agent-runtime](https://github.com/yasuyuki/agent-runtime).
Install the built wheel into a separate clean environment, then use that
interpreter for `tests/test_project.py`. Run installed `agent-rules --version`
and `--help` outside the source tree as CI does. This distinguishes packaged
code/data from imports accidentally satisfied by the checkout.

The installed-entry test also creates one nonce-bearing rule and one skill with
a relative support file from `tests/fixtures/native-e2e/`. It tests the four
consumer outputs in separate disposable projects and the combined output twice
with new nonces. Each round uses the installed CLI for apply, check, unchanged
reapply and empty-source rollback; it checks the ownership manifest, support
file, unowned sentinel and refusal to repair a missing owned support file.
Python 3.12 package jobs additionally install from the checkout with the public
`pip install .` route and run the same fixture. These are placement tests. They
do not assert that a vendor CLI loaded or forgot the rule or skill.

## Native CLI acceptance (#19)

The separate [Native E2E workflow](../.github/workflows/native-e2e.yml) is an
authenticated pilot, not part of the PR gate. It runs only from `main` on a
disposable GitHub-hosted Ubuntu VM and uses the `native-e2e` Actions environment.
That environment has a custom deployment branch policy allowing only `main`;
the workflow also checks the ref. Fork PR code never receives these secrets.
The VM creates an unprivileged `native-e2e` account for the actual vendor CLI,
keeps the fixture controller/source checkout unreadable to it, and retains the
same consumer workspace and profile across fresh native processes. The job
installs all four CLIs for the daily combined cell; the weekly cron adds each
CLI-only cell. It records sanitized JSON per cell.
`tests/native_e2e.py` requires a successful structured terminal event, a
matching challenge and, for the skill probe, a matching proof file plus a
completed helper tool event. Raw model transcripts and keys are not artifacts.

The environment needs four secrets: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GEMINI_API_KEY` and `CURSOR_API_KEY`. Use dedicated test identities/projects,
minimal vendor permissions, spending limits and revocable API keys. Store the
keys as *environment* secrets in GitHub, never in a repository file or a chat.
Claude and Cursor consume their key from the environment; Codex performs
noninteractive API-key login in the isolated profile; Antigravity requires both
the Gemini key and `modelProvider: gemini` in that profile. The environment and
the branch policy are already created; the keys and vendor-side billing access
remain the repository owner's responsibility. See the vendors' [Claude headless](https://code.claude.com/docs/en/headless),
[Codex authentication](https://learn.chatgpt.com/docs/auth),
[Antigravity authentication](https://antigravity.google/docs/cli-install?hl=en),
and [Cursor Actions](https://cursor.com/docs/cli/github-actions) guidance.

The Linux pilot deliberately fails on missing secrets, CLI version drift,
unreadable tool binaries, lost source isolation, missing terminal evidence or
rollback residue. The combined/weekly cells are wired but have no authenticated
run evidence yet. CI separately checks the Windows local-user/ACL isolation
primitive without credentials or a model call. It does not yet cover Windows native execution, supported
user scope, or the first live run.
Those cells are `blocked`/`unverified`, not PASS, until their implementation and
actual authenticated evidence are recorded in Issue #19. GitHub-hosted jobs are
destroyed after each run; they are not persistent managed agent environments,
so the workspace's runtime inventory does not list them.

Run `npm ci --ignore-scripts`, then `python tests/test_rulesync_backend.py` and
`python tests/test_rulesync_export.py` for real pinned-backend generation,
ownership, conflict, deletion, check and rollback coverage. The tests use only
disposable HOME/project roots.

For legacy declaration placement/composition behavior, use the existing
[verification skill](../skills/verify-agent-rules/SKILL.md). It drives disposable
public inputs and keeps evidence; it does not deploy to real environments.
Use `python tests/test_rules.py` for loader/projection regressions and
`python tests/test_verification_skill.py` for failures in that proof mechanism.
The [acceptance record](verification-skill.md) identifies past demonstrations
and unverified surfaces.

## Documentation and regression selection

Run `python tests/docs_check.py` locally for the same maintained local reference
check as CI. [The checker](../tests/docs_check.py) defines the supported Markdown
forms and exclusions; it does not certify semantic quality or crawl Web links.
Use the reader-specific optimization skills for authoring and ordinary review
for related prose when code/help changes.

[ci_changes.py](../tests/ci_changes.py) is the single change classifier and
required-job gate. Known explanatory README/docs changes can omit the heavy
checkout/package regressions; README still requires distribution metadata
build/check. Behavioral or uncertain changes keep full coverage. Do not add
commit-level skip markers to choose jobs manually. PR diffs cover merge-base to
head; pushes cover their complete commit range. Final topic, PR merge and main
runs are distinct evidence.

## Coverage and diagnostics

[The workflow](../.github/workflows/ci.yml) owns exact commands, versions,
partitions and installed-wheel selections. Full CI covers Windows/Linux and
Python 3.10/3.12, with one checkout job and a separate package job per configuration. The four existing `test` gates require successful documentation
checks and either successful heavy matrices or their classification-authorized
skip. Failures, cancellation and unexpected skips cannot satisfy them.

| Boundary | Evidence |
| --- | --- |
| Source behavior | Current source, placement, handoff, inventory, optional-hook and workspace-entry contracts |
| Installed distribution | Build/metadata and project CLI end-to-end checks; imports must resolve outside the checkout |
| Selection and documentation | Whole-range classification, intentional/abnormal skips, and maintained local reference tests |
| Real environment behavior | Separate authorized host acceptance; fixture/byte checks do not establish native agent loading or UI delivery |

The existing `tests/ci_runner.py` retains each case's outcome and elapsed time,
plus available fixture/cleanup and outer Git/CLI measurements. Its `--help`
describes local invocation. Timeouts preserve partial outcomes and terminate
only owned test processes. Lifecycle tests use disposable Git repositories and
independent package environments.

Read failing case output in the normal log and retained `ci-results-*` artifacts.
Artifacts include runtime/dependency identity and source/workflow/run metadata.
Compare matching inputs before reusing evidence; a PR head is not its merge or
integrated main revision. Platform skips remain explicit. Outer command timings
include nested hooks, so summing them does not measure independent CPU work.
Use existing job timestamps for elapsed/runner time and natural runs for
comparisons; do not retry merely to manufacture green results or percentile data.

## Publication

Source installation is documented in the [README](../README.md). Publishing is
a separate explicit release decision: verify package-name ownership, version,
license, distribution contents and required CI before using the authorized
publishing identity. No PyPI upload, tag or GitHub Release is triggered by normal
pushes. If the name changes, update metadata, version lookup and install examples
together. After an authorized publication, verify installation from the actual
distribution source before changing the README's publication status.

## Historical measurements

The following observations and scheduling rationale are retained evidence from
before the documentation selector above; their old job-selection description
is not the current workflow contract.

## Baseline

Successful main run [34737606797](https://github.com/yasuyuki/agent-rules/actions/runs/34737606797)
(`3988e46`) took 1,778 seconds from creation to completion and 4,111 total runner
seconds. First job start was 3 seconds after creation. The preceding successful
run [34737576430](https://github.com/yasuyuki/agent-rules/actions/runs/34737576430)
took 1,753 seconds and 4,023 total runner seconds. Windows branch/recovery and the
wheel composite step were the dominant costs; the composite is not build time.
These are individual runs, not a p50/p95 estimate.

## Historical scheduling rationale (before documentation selection)

The source/handoff/rules contracts run in checkout partition 0; both partitions
run their disjoint part of the complete real-Git collection. Package jobs have
no dependency on checkout tests: each builds its own sdist and wheel, performs
strict metadata validation, and runs the entire installed project suite and the
same three wheel-specific E2Es. Separate runners isolate build output, source
hash checks, installed environments and every mutable Git fixture. There is no
artifact transfer or shared mutable checkout between verification jobs.

The four existing `test (<os>, <python>)` check names are retained as gates. Each
waits for **all** checkout partitions and package configurations, including
artifact upload, and accepts only `success` for both matrices. Failure,
cancellation or an unexpected job skip cannot satisfy the gate. Matrix fail-fast
remains disabled. Source-stage skips in checkout partition 1 are intentional:
those contracts run once per OS/Python configuration in partition 0. Platform
case skips remain explicit in the JSON. Checkout artifacts now include the
partition number; package artifacts have a separate name.

`tests/ci_checkout_weights.json` contains only test IDs and relative weights
from integrated main run #125 (`34764799630`, `8bc1e6a`). For each of Windows
3.10 and 3.12, case duration is normalized by the suite total; the larger of the
two normalized observations is used. Longest-weight-first assignment breaks
ties by test ID and then bucket index. Timings affect ordering and assignment,
never collection or eligibility; absent/new/invalid measurements fall back
without excluding cases. Recovery still uses its existing `load_tests`.

Saved #125 JSON gives the following scheduling estimates. They reuse measured
case durations, and are **not** predictions of contention or runner startup:

| Layout | Windows 3.10 longest bucket | Windows 3.12 longest bucket |
| --- | ---: | ---: |
| Existing ID-stride, 3 workers | 356.8 s | 268.5 s |
| Weighted, 3 workers | 309.1 s | 233.8 s |
| Weighted, 4 workers on one runner | 232.3 s | 175.4 s |
| Weighted, two runners × 3 workers | 156.9 s | 116.2 s |

Three workers cannot reach five minutes on 3.10 even with perfect balancing
(the average lower bound is 306.3 seconds before other work). Four workers on
one runner with the existing serial package path still project over five
minutes (232.3 + 124 seconds); making package work concurrent on that runner
would also compete for CPU and require build/source isolation. Two checkout
runners preserve the measured three-worker concurrency on each host and remove
the package dependency, at the cost of extra startup and checkout operations.
Actual run/job/step timestamps and summed runner seconds must measure that cost.

The longest retirement case was inspected separately: consolidating its
unfinished/dependent and untracked/ignored fixtures could save roughly three
outer CLI and four outer Git invocations while retaining assertions. This alone
cannot remove the observed 182-second gap to the target. It changes scenario
setup and is deferred in favor of scheduling-only changes. Cherry-pick fixture
reuse would add sequencer-abort coupling. No production engine, fixture,
assertion, lock, fsync or validation cache is changed in this follow-up; existing
legacy-hook and inspection-path negative regressions remain in the full suite.

## Deterministic fixture boundaries (#124)

The September 16 investigation separated the saved PowerShell parser startup
failures (already addressed by #119's child-only telemetry opt-out) from the
remaining causes. The checkout/package matrices and worker counts stay intact:
the evidence identified fixture and dependency-lock boundaries, not a need to
remove platform coverage or serialize every real-Git contract.

* The descendant-pipe test previously required two Python processes and parent
  exit within 150 ms, then raced `/proc/<pid>/stat` existence against process
  reaping. It now observes the real leader's exit before starting the unchanged
  pipe-drain budget and treats ENOENT/ESRCH during procfs reads as completed exit.
  A deterministic clock test separately checks the shared wait budget and bounded
  cleanup; runner scheduling speed is not a product latency requirement. The
  live subprocess test still requires the pipe-open error and descendant death.
* Parallel installs into independent repositories can share one linked source.
  Dependency locking accepts a failed native lock command only if the native
  lock postcondition now exists, preserving a concurrent installer's lock.
  The source validation suite forces concurrent callers past the initial check
  against a disposable real linked worktree. Existing-lock preservation and
  failure without a completed lock remain checked. No dependency is unlocked.
* The filter-lock adoption fixture writes and commits exact LF bytes before
  applying `-text`, which otherwise preserves a platform-dependent CRLF base
  blob. Exact filtered bytes and unlocked filter execution are still required.
  Separate CRLF preservation cases remain in both checkout and installed-wheel
  coverage.

Local full regression additionally exposed a POSIX terminal fixture's asynchronous
SIGINT/pause scheduling race (also reproduced without the managed entry). The vendor now blocks SIGINT before announcing
TTY readiness and consumes the pending signal with `sigwait`; the real standard
entry, all three TTY descriptors, and signal-derived exit status remain checked.
The pack-refs repair regression also asserts the product-owned configuration
refusal instead of Git's version-dependent English spelling of "reference";
pack-refs failure, successful repair, and unchanged semantic refs remain required.

The regression tests use the existing source regression stage and remote
adoption collection; no new job, retry, skip, deadline increase, or failure
suppression is introduced. The parent-exit fixture setup is bounded by the
existing CI runner timeout rather than the product's pipe-drain deadline.
Investigation, before/after evidence, final revisions and residual limitations
are recorded in [work-records #124](https://github.com/yasuyuki/work-records/issues/124).
This removes the identified causes; finite validation does not establish that
host scheduling, future dependency updates or external services can never fail.

## Agent report observation

Live validation on 2026-09-08 (Linux, Python 3.14.4) used the existing public
launch entry point, Codex 0.153.4 and Claude Code 2.1.263. Both returned valid
partial inventories, including explicit unknowns, and produced HTML tables.
The target's pre-existing instruction/configuration files were unchanged after
the diagnostic. Cursor was unavailable through that environment's launcher;
its failure was isolated and recorded in the same report. Real report data and
launch configuration remain outside this repository. These observations do
not establish completeness of the agents' self-reports or absence of startup
side effects outside the target.

Workspace lifecycle source/build/tests are owned by the independent
[workspace-lifecycle repository](https://github.com/yasuyuki/workspace-lifecycle).
Checkout compatibility tests install its explicit fixed public source artifact;
this CI does not build or run a local lifecycle package suite. Runtime composition
and Windows console tests belong to
[agent-runtime](https://github.com/yasuyuki/agent-runtime).
