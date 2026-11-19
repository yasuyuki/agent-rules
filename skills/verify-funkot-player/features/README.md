# Verified feature scope

| Behavior | Entry point | Recipe |
| --- | --- | --- |
| Select a playlist occurrence, request removal, and request Undo with the returned identity | Real Svelte UI in Chromium, synthetic Tauri IPC | [Playlist removal and Undo](playlist-undo.md) |
| Delete the playlist shown as the playback source from its menu, with the switch note and an in-dialog failure | Real Svelte UI in Chromium, synthetic Tauri IPC | [Source playlist deletion](playlist-delete.md) |

Other playlist operations, library tags, native persistence and restart, audio
output, OS dialogs, Android controls, and Windows WebView2 are not-run.
