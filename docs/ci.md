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
then sorts and partitions IDs among three child processes. Recovery's
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
