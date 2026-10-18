# Related public repositories

Use this index to choose the repositories and change order for work that spans
more than one public repository. Each repository's own README remains the
authority for its responsibility; if they disagree, follow that README.

This index lists public repositories only. Private configuration and records
are indexed separately and are not named here.

## Responsibilities

### Agent foundation

| Repository | Owns | Uses |
| --- | --- | --- |
| [agent-rules](https://github.com/yasuyuki/agent-rules) | Common rules, project-specific skills and the Rulesync placement CLI (`apply`, `check`, `preview`) | agent-skills, workspace-lifecycle (read-only inventory import) |
| [agent-skills](https://github.com/yasuyuki/agent-skills) | Generic reusable skills | — |
| [agent-runtime](https://github.com/yasuyuki/agent-runtime) | Standard `codex`, `claude` and `grok` launch and the HANDOFF receiver | workspace-lifecycle (SHA-256 pinned CLI) |
| [workspace-lifecycle](https://github.com/yasuyuki/workspace-lifecycle) | Task worktree creation, supervised runs, integration and retirement | — |
| [necessity-review](https://github.com/yasuyuki/necessity-review) | Command necessity review for native Codex hooks | — |
| [agent-telemetry](https://github.com/yasuyuki/agent-telemetry) | Local OTLP log collection into SQLite for Codex and Claude Code; standalone, intended for use by rule experiments | — |
| [agent-at](https://github.com/yasuyuki/agent-at) | Scheduled agent launch | — |
| [rule-experiment-apparatus](https://github.com/yasuyuki/rule-experiment-apparatus) | Rule experiment protocol, schemas and cycle CLI | agent-telemetry, agent-runtime, workspace-lifecycle |

### Funkot (local only)

These repositories process audio and some integrate with Windows
applications. Work on them in a local environment, not in cloud sessions.

| Repository | Owns | Uses |
| --- | --- | --- |
| [funkot-autodj](https://github.com/yasuyuki/funkot-autodj) | `funkot-core` and its CLI | — |
| [funkot-player](https://github.com/yasuyuki/funkot-player) | Player application and its current-track API; a client of the agent foundation tools that can be developed without them | funkot-autodj (commit pinned in `funkot-core.commit`) |
| [dj-live-text](https://github.com/yasuyuki/dj-live-text) | Windows live text display for DJ streams | funkot-player (current-track API) |
| [funkot-calendar](https://github.com/yasuyuki/funkot-calendar) | Party event ledger and ICS feed | — |

## Change order

Change a used repository before its users, then update every pin that names
the changed revision. Known pins:

- workspace-lifecycle is pinned by agent-runtime configuration and by this
  repository's CI.
- agent-telemetry is pinned by rule-experiment-apparatus CI.
- funkot-autodj is pinned by `funkot-core.commit` in funkot-player.

The [coordinate-repository-versions](https://github.com/yasuyuki/agent-skills/tree/main/skills/coordinate-repository-versions)
skill audits cross-repository compatibility and plans pin changes and rollback.

## Cloud sessions

Public repositories can be read in a cloud session without attaching them.
Attach a repository only when the session must push to it or open pull
requests. Start from the repository that owns the change:

| Work | Start with | Add when needed |
| --- | --- | --- |
| Rules, skills and placement | agent-rules | agent-skills |
| Runtime or lifecycle release | agent-runtime or workspace-lifecycle | agent-rules |
| Rule experiments | rule-experiment-apparatus | agent-telemetry |

Do not copy private repository content, personal paths, host names or
credentials into public commits, pull requests, comments or documentation.
