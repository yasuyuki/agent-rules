---
name: verify-funkot-autodj
description: >-
  Verify Funkot AutoDJ's offline CLI playlist rendering, transition-only WAV,
  and analysis-cache creation with synthetic tracks and retained evidence.
  Use for engine CLI verification, not live playback or listening acceptance.
---
# Verify Funkot AutoDJ

Verified on Linux with Codex against engine revision `5b00c2f`, including a
fresh-session replay. The proof challenges reject silent output, missing cache
side effects, and a successful completion command that does not reclaim its WAV.
Every later run needs new evidence. This result does not certify another revision.

Select an explicit standalone `funkot-autodj` checkout. Read its `AGENTS.md`,
`README.md`, and `CONTEXT.md` when present. The selected proof uses two synthetic
tracks through the actual `-l --render` CLI. It checks WAV samples and files,
transition-window export, and the persisted analysis cache. It uses no audio
device, private music, embedding host, or player UI.

## Launch and doctor

Run on Linux with Python 3.11+, Git, Cargo, Rust, and the target's native build
dependencies already available. Use the target's documented host-Cargo route
only where that environment permits it. Otherwise this recipe is blocked.
It installs no toolchain, package, Docker image, or agent. Dependency downloads
may occur through locked Cargo builds. Builds use the selected Cargo target
directory and preserve that shared cache.

From the selected engine root, set `verification_skill` to the absolute directory
containing this SKILL.md. Set `cargo_target` to the environment's existing Cargo
target directory. Set `evidence_root` to a persistent private directory outside
the checkout and target directory. Set `driving_agent` to the actual agent.

```sh
python3 "$verification_skill/scripts/verify.py" --repo "$PWD" \
  --target-dir "$cargo_target" --evidence-root "$evidence_root" \
  --agent "$driving_agent" --doctor-only
python3 "$verification_skill/scripts/verify.py" --repo "$PWD" \
  --target-dir "$cargo_target" --evidence-root "$evidence_root" \
  --agent "$driving_agent"
```

The helper's `--help` defines its arguments. Doctor saves the exact revision,
dirty state, tracked Cargo/source hashes, runtime versions, and expectations.
Doctor creates only its evidence record. It does not compile or drive the CLI.
Uncommitted Cargo or crate inputs block execution. Unrelated changes are recorded.

The full recipe builds the actual CLI and existing `gen_synth` example with
`cargo build --locked --release`. It records their paths and hashes before use.
No server or readiness endpoint exists. Successful build and executable identity
are preparation. They do not count as the feature result.

## Drive and evidence

Read [the offline feature](features/offline-render.md) before Drive.
The helper creates a new scratch directory and invokes the existing generator
there. It writes a relative-path playlist for the first two generated tracks,
selects a fresh cache, and renders the full mix followed by `--transitions-only`.
Preparation uses `--jobs 2 --render-speed 0` so the loader's wall-clock race
does not decide whether the second track is ready.

Expectations are saved before Drive. The helper independently parses the WAV
headers and samples. It checks nonzero finite stereo float32 output at 44100 Hz,
a mix longer than 60 seconds, exactly one nonempty transition clip, and a shorter
transition-only WAV with the same samples as that clip. It verifies two complete
cache entries tied to the original track identities and current cache version.
The duration bounds come from the target's CLI integration test contract.
It records peak and samples above unity without imposing a limiter expectation.

Read the printed `result.json` and retained `observations.json`. Command logs,
the playlist, source and executable hashes, fixture hashes, WAV hashes and
metrics, and cache contents remain in a unique run directory under the evidence
parent. WAV and fixture bodies are temporary because this proof does not require
listening. Existing target contents, music, labels, and caches remain untouched.

## Judge and clean up

`pass` requires all declared observations. `fail` means an executed operation
or an evidence assertion failed. `blocked` means a prerequisite prevented Drive.
`not-run` means Doctor only. Exit codes are 0, 1, 2, and 3 respectively.
Feature and cleanup results are separate. Failed cleanup makes the overall
result fail even when feature observations pass.

The helper waits for its commands and closes each owned process group. On a
successful proof, it calls the target's public `--artifact-complete` entry for
each owned WAV generation with the accepted observations and final-use record.
It retains each reclaimed receipt and hash before removing its scratch directory.
It verifies retained evidence after cleanup. It preserves the selected
Cargo cache because other work may use it. On interruption, inspect that run's
record for its exact scratch path and process-group ownership before recovery.
Never kill by process name or delete another run's resources.

If a failed native run leaves unaccepted WAV generations, the helper retains
them at the recorded scratch path and reports failed cleanup. Follow the target's
`docs/local-data.md` acceptance boundary before reclaiming them. A fixture-only
challenge without native generations removes scratch while retaining its manifest.
Neither result is a completed native proof with successful cleanup.

Report revision, agent, feature result, cleanup result, and evidence path.
[The feature-map](features/README.md) names the other entry points and limitations.
Synthetic file checks do not establish real-track musical quality, beat or
four-bar alignment, navigation, live audio, platform acceptance, or release safety.
