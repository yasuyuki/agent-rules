# Development, verification and CI

Use an active Python environment in the checkout root. To build the sdist and
wheel and validate their metadata:

```console
python -m pip install build twine
python -m build
python -m twine check --strict dist/*
```

The build makes the wheel from the sdist. Distributions include the shared
engine and tool conventions, not the maintainer's rule/skill catalog.
Install the built wheel into a separate clean environment, then use that
interpreter for `tests/test_project.py`. Run installed `agent-rules --version`
and `--help` outside the source tree as CI does. This distinguishes packaged
code/data from imports accidentally satisfied by the checkout.

For placement/composition/mirror behavior, use the existing
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
Python 3.10/3.12, with two checkout shards per configuration and a separate
package job. The four existing `test` gates require successful documentation
checks and either successful heavy matrices or their classification-authorized
skip. Failures, cancellation and unexpected skips cannot satisfy them.

| Boundary | Evidence |
| --- | --- |
| Source behavior | Full branch/recovery/operation/remote-adoption suites and the source, placement, handoff, inventory and optional-hook contracts |
| Installed distribution | Build/metadata, project CLI end-to-end checks, packaged hook/data and representative real-Git cases; imports must resolve outside the checkout |
| Selection and documentation | Whole-range classification, intentional/abnormal skips, and maintained local reference tests |
| Real environment behavior | Separate authorized host acceptance; fixture/byte checks do not establish native agent loading or UI delivery |

The existing `tests/ci_runner.py` retains each case's outcome and elapsed time,
plus available fixture/cleanup and outer Git/CLI measurements. Its `--help`
describes local invocation. Timeouts preserve partial outcomes and terminate
only owned test processes. Tests keep independent mutable Git fixtures; weights
in `tests/ci_checkout_weights.json` affect scheduling, never eligibility.

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

The regression tests use the existing necessity/source stages and remote
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
