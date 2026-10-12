---
name: verify-funkot-player
description: Verify Funkot Player's playlist removal and Undo requests through its browser UI, with synthetic IPC, retained screenshots, and isolated cleanup. Use for frontend verification, not native playback or persistence acceptance.
license: MIT
---

# Verify Funkot Player

Verified on Linux with Codex against player revision `666fc4b`, including a
fresh-session replay and a wrong-Undo-response challenge. Each future run
requires its own evidence; this result does not certify another revision.

Use an explicitly selected `funkot-player` checkout. Read its `AGENTS.md`,
`CONTEXT.md`, `.claude/skills/ui-design/SKILL.md`, and `docs/ui-design.md`.
The [feature index](features/README.md) defines the proven boundary.

## Run the browser proof

Run on Linux with Python 3.12+, Git, Node.js, npm, and the Chromium runtime
required by the target's pinned Playwright package. The host must already
provide Chromium system libraries. This recipe needs npm registry and
Playwright download access when their caches are empty. It installs no agent,
native app, audio engine, Docker image, or system package.

From the selected player root, set `verification_skill` to the absolute directory
containing this SKILL.md. Use a persistent, private evidence parent outside the
checkout and temporary directories. Pass its absolute path as `evidence_root`.
Identify the actual driving agent in `driving_agent`.

```sh
python3 "$verification_skill/scripts/verify.py" --repo "$PWD" \
  --evidence-root "$evidence_root" --agent "$driving_agent" --doctor-only
python3 "$verification_skill/scripts/verify.py" --repo "$PWD" \
  --evidence-root "$evidence_root" --agent "$driving_agent"
```

The helper's `--help` defines its arguments. Doctor records the exact committed
frontend inputs, revision, dirty state, runtime versions, and port availability
without launching the app. Uncommitted frontend changes are blocked. Commit
the intended candidate through its normal workflow before using this recipe.
Unrelated changes remain recorded and are not copied.

The complete run exports those frontend inputs into a new temporary directory,
runs `npm ci`, installs the pinned Chromium browser into that directory, and
uses the existing `npm run ui:capture` entry. Playwright owns its fresh browser
and Vite server on loopback port 1422. Its configuration refuses a borrowed
server. The helper clears inherited Tauri host overrides for this run.

Read [the selected feature](features/playlist-undo.md) before Drive. Expectations
are saved before launch. The helper checks both configured viewports, exact test
identity, assertion results, and screenshot files. It retains the JSON report,
command logs, input hashes, and screenshots outside scratch state.

## Judge and clean up

Read the printed `result.json`. Check `feature_result`, `cleanup.ok`, and the
referenced artifacts after cleanup. Inspect both screenshots against the target's
UI review criteria and write findings in the same evidence directory. The helper
does not claim visual approval from a successful capture.

`pass` means the selected browser assertions and artifacts passed. `fail` means
an executed assertion, evidence, or cleanup check failed. `blocked` means a
prerequisite prevented Drive. `not-run` means Doctor only. Exit codes are 0, 1,
2, and 3 respectively. A failed cleanup makes the overall result fail even if
the feature passed. Never reuse a previous run as current proof.

Playwright shuts down its browser and server. The helper removes only its new
scratch directory, including downloaded browser files and dependencies. It
checks that the port is free and retained artifacts still exist. After an
interrupted helper, inspect its record and exact owned process group before
recovering that run. Never kill a process by name or delete another run's data.

Report the selected revision, agent, feature and cleanup results, screenshot
findings, and evidence path. Native IPC, disk persistence, audio, OS dialogs,
Windows WebView2, and Android remain not-run. This skill changes no product
source and does not certify a release.
