---
name: @SKILL_NAME@
description: Answer a native E2E skill probe using the included support file.
---
# Native E2E skill probe

For a request explicitly asking to use this skill, execute `proof.py` with the
environment's Python interpreter, the requested challenge and a JSON output
path in the disposable workspace. The script reads `support.txt` relative to
itself. Read the resulting JSON and return its `skill` and `challenge` fields.
