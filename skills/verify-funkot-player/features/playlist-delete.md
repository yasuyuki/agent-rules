# Source playlist deletion

The user deletes the playlist that is both displayed and the playback source,
without switching to another source first. The delete dialog says playback
will switch to the queue. A refused request is reported inside the dialog,
next to its actions, and the dialog stays open. Use the player's `CONTEXT.md`
terms: the source (再生元) and the queue (再生待ち) differ from the list being
displayed.

## Contract and operation

In the selected checkout, inspect these existing sources before running:

- `tests/ui/playlist.spec.mjs`, test `the displayed source list is deleted from its menu and the dialog explains the switch and failures`.
- `tests/ui/fixture.ts`, the default `queue_state` source `night` and `failNext`.
- `src/components/Queue.svelte`, the menu's Delete action, `confirmDialog` and the dialog's `role="alert"` paragraph.
- `src-tauri/src/playlists.rs` `Catalog::delete` and `command_with` in `src-tauri/src/playlist_service.rs`, which switch the source to the queue in the same request. The browser run does not execute them.

The helper runs this test in the same `npm run ui:capture` invocation as the
other features, selected by its exact title from `tests/ui/playlist.spec.mjs`.
The narrow project first clicks the `Up next` tab.

Drive uses only rendered controls:

1. Open `Playlist actions` and click `Delete` while `night` is the source.
2. The `Delete` dialog shows `Playback will switch to the queue.`
3. Type the full list name. The fixture fails the next `playlist_command` with
   code `busy`. Click `Delete`.
4. The dialog stays open and its alert reads `Playlist editing is busy.` in the
   viewport. Capture `delete-source-failure`.
5. Click `Delete` again. The dialog closes. Exactly two `playlist_command`
   requests carry `{"kind":"delete","id":"night","confirm_name":"Night set with an intentionally very long name"}`
   and no `select` request precedes them.

Both projects must pass without skips or retries. Inspect both
`delete-source-failure` screenshots for the note, the alert and both actions
inside the dialog.

## Evidence and limits

`result.json` records the expected commands with the other features.
`playwright.json` links the screenshots under `results/`.

The fixture accepts the second delete without changing its source or catalog.
A pass proves the UI sends a delete for the active source with no prior
`select`, shows the switch note, and reports a failure inside the dialog. It
does not prove the native source switch, saved deletion, or that audio keeps
playing. The player's Rust tests
`deleting_the_source_playlist_returns_to_the_normal_queue_in_one_command` and
`deleting_the_source_returns_the_source_to_the_normal_queue` cover those.
