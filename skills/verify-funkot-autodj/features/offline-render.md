# Offline playlist render

Verified on Linux with Codex against engine revision `5b00c2f`.
Execute the [skill recipe](../SKILL.md) with a new evidence directory for later runs.

## Behavior and entry point

A user supplies a playlist and receives a complete stereo WAV, one trial-listening
clip per transition, and reusable analysis-cache entries. `--transitions-only`
exports the same windows without the rest of the mix.

The helper invokes the actual `funkot-autodj -l --render` binary built from the
selected committed source. Fixtures come from the existing `gen_synth` example.
The playlist includes comments, a blank line, and relative paths. It contains
`track_a_180_i16_o16.wav` and `track_b_178_i32_o8.wav` in that order.

## Operations and observations

1. Generate synthetic tracks in this run's scratch directory.
2. Render `mix.wav` with a fresh `--cache-dir`, `--wav-format f32`,
   `--sample-rate 44100`, `--jobs 2`, `--render-speed 0`, `--no-loop`, and
   `--transition-clip-seconds 60`.
3. Render `only.wav` with the same inputs and `--transitions-only`.
4. Check both WAVs and the one WAV under `mix_transitions/`. Each has finite,
   nonzero stereo float32 samples at 44100 Hz. The full mix is longer than
   60 seconds. The clip is longer than 0.5 seconds. `only.wav` is shorter
   than the mix and has exactly the exported clip's sample data.
5. Check two JSON caches under the isolated cache directory. Their names match
   the original tracks' content identities. Version, file identity, positive
   frame counts, tempo, and section lengths are valid. Reanalysis is not pending.
6. Retain observations, contents of both caches, command logs, and hashes.
   Remove owned scratch state and confirm those records still exist.

The full interpreter invocation, cwd, build prerequisites, preparation, judgment,
and cleanup are in [SKILL.md](../SKILL.md). `scripts/verify.py` requires only the
Python standard library and the declared external build tools.

## Contract sources

Resolve these paths from the selected Funkot repository root.

| Contract | Source |
| --- | --- |
| Offline WAV format, statistics, windows and transition-only semantics | `README.md`, `funkot-cli/src/main.rs` |
| End-to-end mix, clip format and duration assertions | `funkot-cli/tests/cli.rs`, `render_two_tracks_end_to_end` |
| Transition-only output is shorter | `funkot-cli/tests/cli.rs`, `render_transitions_only_is_shorter_than_full_mix` |
| Relative playlist paths and comments | `funkot-cli/src/playlist.rs`, `funkot-cli/tests/cli.rs` |
| Synthetic input recipes | `funkot-core/examples/gen_synth.rs` |
| Track identity and cache version | `funkot-core/src/cache.rs` |
| Analysis field meaning | `funkot-core/src/lib.rs`, `TrackAnalysis` |

## Limits

This is a file-render proof on synthetic Funkot-style music. Audio decoding,
analysis, stretching, and mixing execute in the real engine. Input music is
synthetic. No external audio-device boundary executes. The proof confirms the
window-export relationship without judging how its musical transition sounds.

Real music, listening, downbeat and four-bar alignment, live keys, integer WAV,
other codecs, manual-cache maintenance, labels, survey, C ABI, Windows, and
Android are not-run. A regenerated cache with plausible numbers does not prove
analysis accuracy or preservation of manual annotations.
