# Playlist removal and Undo

The user selects one occurrence of a repeated track, removes that occurrence,
and invokes Undo. A track and its occurrence are different identities. Use the
player's `CONTEXT.md` terminology. Browsing a playlist does not itself select
the playback source.

## Contract and operation

In the selected checkout, inspect these existing sources before running:

- `tests/ui/queue-ui.spec.mjs`, test `playlist removal keeps Undo and a poll retains the selected occurrence`.
- `tests/ui/fixture.ts`, synthetic `queue_state` and `playlist_command` responses.
- `src/components/Queue.svelte`, removal and Undo handlers.
- `docs/ui-design.md`, browser verification and native boundary.
- `README.md`, the named playlist's saved order and playback position.

The helper runs this exact existing entry in its isolated frontend copy:

```sh
npm run ui:capture -- tests/ui/queue-ui.spec.mjs \
  --grep 'playlist removal keeps Undo and a poll retains the selected occurrence' \
  --reporter=json --output "$run_evidence/results"
```

`PLAYWRIGHT_JSON_OUTPUT_NAME` points to that run's `playwright.json`.
Preparation and readiness are owned by `playwright.config.mjs`. Vite serves
`http://127.0.0.1:1422/tests/ui/`; the page must show `section.queue`.
The narrow project first clicks the `Up next` tab.

The existing test selects the first `Select Pulse` button and simulates an
incoming revision before Drive. That setup tests selection retention, not a
user mutation. Drive uses only rendered controls:

1. The selected occurrence remains labelled `Pulse` after the revision changes.
2. Click `Remove Pulse from this playlist` in the selection toolbar.
3. Exactly one `playlist_command` carries
   `{"kind":"remove","id":"night","entry_id":"a"}`.
4. Click `Undo`. Exactly one additional command carries
   `{"kind":"undo_remove","undo_id":"undo-1"}`.
5. The Undo button disappears. Capture the resulting viewport.

Both desktop and narrow projects must pass without skips or retries. Inspect
the two attached `playlist-undo` screenshots. A zero process exit with absent,
wrong, skipped, or incomplete results is a failure.

## Evidence and limits

`result.json` fixes expectations and lists commands, revision, source hashes,
runtime, owned resources, results, and cleanup. `playwright.json` records each
test outcome and links screenshots under `results/`. Logs retain failures.
Evidence survives removal of the temporary frontend, node modules, and browser.

The fixture returns a fixed Undo identity and records IPC requests. It does not
persist removal or restore saved rows. A pass proves request identity, selection
retention, and visible Undo feedback. It does not prove native deletion,
restoration, disk writes, playback, or real music-file handling. No real music
or profile is used, and there is no required native persistent side effect.

To challenge failure detection, copy the committed frontend into a disposable
test repository. Change only its fixture's `undo_id` response from `undo-1` to
`wrong-undo`, commit that synthetic input, and run the same helper. The mock
operation still succeeds, but the real frontend sends the wrong identity and
the unchanged test must fail. Keep the failed report and confirm cleanup.
Never mutate a live checkout for this challenge.
