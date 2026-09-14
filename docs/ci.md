# CI evidence and runtime

CI keeps Linux/Windows × Python 3.10/3.12. Pushes to topics without a PR still
run; pull-request merge results and integrated main are separate evidence.
The last 30 runs inspected on 2026-09-13 contained 29 push events and one dynamic
event, no PR events and no duplicate SHA runs, so no event suppression was added.
Concurrency replaces only the same workflow/event/repository/PR-or-ref.
`fail-fast: false` obtains all four outcomes; cancellation is never a pass.

## Coverage allocation

| Contract | Checkout | Installed wheel |
| --- | --- | --- |
| Ref/commit/push rejection, remote identities, one-use merge/pick/tag approval, worktree protection and non-destructive retirement | Entire `test_branch_management` | Real unregistered-ref/no-verify/alternate-index rejection scenario |
| Remote-only adoption at verified Q with historical B, contents and tracking | Real-Git adoption and interruption tests in branch/recovery suites | `test_remote_only_adopt_pins_verified_tip_and_historical_base` |
| Crash recovery, locks, concurrent operations, legacy-hook mutation revalidation | Entire `test_branch_recovery`, collected through its existing `load_tests` | Same shipped branch engine, exercised through installed hooks |
| Existing hook arguments/status and modified-hook detection | Entire branch suite | `test_install_preserves_an_existing_hook_and_detects_tampering` |
| Source-only inventory catalog versus installed branch engine (previous wheel regression) | Entire branch suite | `test_declare_agent_updates_only_a_registered_source_catalog` |
| Imports, package data, project CLI apply/check/update and non-destructive failures | Existing source tests | Entire `test_project`, installed in a clean venv; subprocess cwd is outside checkout |
| Build from sdist, wheel metadata, installed entry point | Build and strict twine check | Installed `--version`/`--help` outside checkout in addition to E2E |
| Inspection paths, ignore/no-Git/untrusted/missing discovery, private diagnostic redaction | Entire inventory inspection suite on all four configurations | Packaged engine shares source |

No existing assertion or real-Git scenario was removed. Each heavy test retains
its own remote, index, worktrees, registration, hooks and approval tickets.
Fixture seeding was not changed: traced repeated installation reads dominated
process counts, while a shared seed would remove only a few setup processes.
The dispatcher bytes, fsync, locks, source hashes and remote/ref checks remain.
Git config reads are batched within one validation, never cached across hooks
or mutations. Without an external legacy hook validation and enforcement share
one lock scope; an executed pre-legacy hook is followed by a fresh validation.

## Diagnostics and reuse

`tests/ci_runner.py` collects explicit unittest modules through their loaders,
then assigns all collected IDs to six duration-balanced buckets, split across
two independent checkout jobs with three child processes each. Recovery's
`load_tests` prevents inherited base tests from being run again. The JSON records
per-test status/elapsed time, fixture/cleanup times and outer Git/CLI invocation
counts and durations. Outer command durations include nested hooks: they are not
an independent CPU-time breakdown. Trace2 baseline counts likewise exclude the
dependency probes that deliberately strip `GIT_*`; neither measure attributes
unmeasured fsync or lock costs.

Test starts/ends and tracebacks stream immediately. JSON records are persisted
after each case. A bounded child process group is terminated on timeout, with
its actual exit code and unfinished test retained. This applies only to the CI
helper, never ordinary user Git commands. Existing OS-specific skips remain
explicit `skip` records, not passes. Missing results, collection errors, failures
and timeouts fail the stage. Metrics contain numeric observations and test IDs;
CLI output stays in the normal test log rather than the timing artifact.

The matrix uploads results on success and failure, including resolved build
packages, Python/Git versions and GitHub SHA/workflow/run identity. Compare the
same SHA, workflow, dependency inputs and environment before reusing a result;
never substitute a PR head for its merge SHA or an integrated main SHA. Inspect
all four completed job conclusions and artifact outcomes, not just run status.
GitHub's run/jobs API provides queue-inclusive wait, job start/end and step times.
Sum job durations for runner time; do not sum overlapping nested command timings.
Use natural successful runs for comparisons; do not retry merely to get green
or manufacture percentile samples. With few observations report individual values.

## Baseline

Successful main run [34737606797](https://github.com/yasuyuki/agent-rules/actions/runs/34737606797)
(`3988e46`) took 1,778 seconds from creation to completion and 4,111 total runner
seconds. First job start was 3 seconds after creation. The preceding successful
run [34737576430](https://github.com/yasuyuki/agent-rules/actions/runs/34737576430)
took 1,753 seconds and 4,023 total runner seconds. Windows branch/recovery and the
wheel composite step were the dominant costs; the composite is not build time.
These are individual runs, not a p50/p95 estimate.

## Five-minute integration follow-up

The source/handoff/rules contracts run in checkout partition 0; both partitions
run their disjoint part of the complete real-Git collection. Package jobs have
no dependency on checkout tests: each builds its own sdist and wheel, performs
strict metadata validation, and runs the entire installed project suite and the
same four wheel-specific E2Es. Separate runners isolate build output, source
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
