# Funkot AutoDJ feature-map

The first proven behavior is [offline rendering](offline-render.md).
Each run reports its own result. The entries below distinguish that proof from
known entry points needing another environment or a separate recipe.
Domain terms are defined in the selected engine's `CONTEXT.md`.

| User-visible behavior | Entry point and prerequisite | Operation and expected observation | Side effects and contract source | Coverage |
| --- | --- | --- | --- | --- |
| Render a playlist mix and matching transition-only windows | CLI `-l --render`, Linux native build dependencies | [Offline render recipe](offline-render.md) checks actual WAV samples and both track identities | Isolated WAVs, transition clips, cache JSON. `README.md`, `funkot-cli/tests/cli.rs`, `funkot-core/src/cache.rs` | Verified recipe on synthetic inputs |
| Hear a continuous mix and pause or navigate | Host CLI, audio device and interactive terminal | Play with `--no-loop`. Enter pauses and resumes. Left and right single or multiple taps request the documented entry or intro | Device output and analysis cache. `README.md`, `funkot-cli/src/main.rs`, `docs/transition-phase.md` | not-run |
| Judge real-track transitions | Real-track playlist and listening environment | Render with an empty cache, listen to every exported transition clip, judge downbeats, four-bar starts, silence drops and previous-track residue | Private music, WAVs and cache. `AGENTS.md`, `docs/transition-phase.md` | not-run |
| Maintain automatic analysis while preserving manual bar choices | CLI `--purge-auto-cache --fill-missing-cache`, disposable cache with manual entries | Complete entries are skipped. Automatic entries are removed or rebuilt. Manual-side values survive reanalysis | Cache JSON changes. `README.md`, `funkot-core/src/cache.rs` | not-run, creation alone is covered above |
| Label intro and outro structure | `--label-sections --labels FILE`, terminal and audio device | Choose section candidates and save. Inspect the structural labels and preserved manual intro value | Labels TSV and cache. `docs/labeling.md`, `funkot-cli/src/main.rs`, `funkot-core/src/labels.rs` | not-run |
| Export candidate clips or survey the outro beat grid | `--label-sections --render-clips DIR` for export. `--survey --survey-out FILE` requires audio and terminal | Export click clips or record a one-key grid judgment. Survey skips already judged track identities | WAVs or survey TSV. `funkot-cli/src/main.rs`, `funkot-cli/src/label_session.rs` | not-run |
| Decode other formats or write integer WAV | CLI file arguments and `--wav-format s24` or `s16`. FFmpeg is required for conversion fallback | Render each chosen codec or format and inspect decoded output and sample format | Conversion cache, WAVs and analysis cache. `README.md`, `funkot-core/src/decode.rs`, `funkot-cli/src/wav_write.rs` | not-run |
| Embed the engine and pull audio | C ABI host built for the selected platform | Create an engine, render stereo frames, poll events and free the engine through the public header | Host-owned audio output and cache. `include/funkot.h`, `funkot-core/src/ffi.rs` | not-run |
| Accept and reclaim generated WAVs | CLI `--artifact-complete`, exact generation and proof references | Reclaim only a generation whose acceptance and final use are complete. Keep its receipt and output hash | WAV removal and retained ownership receipt. `docs/local-data.md`, `funkot-core/src/owned_wav.rs` | Used for successful proof cleanup, refusal behavior not-run |

Windows distribution, Windows audio, Android embedding, and the separate Funkot
Player UI are not-run. `./work.sh --self-check` and Cargo suites are preparation
or regression evidence. They do not promote these rows to pass.
