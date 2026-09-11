# agent-rules Feature Map

| Feature | User entry point | Scope |
| --- | --- | --- |
| [Placement and safe update](placement.md) | `python3 bin/place.py apply/check --declaration ...` | One disposable local project; Codex file convention, independent of the driving agent |
| [Dependent source composition and mirror](dependencies.md) | Repeated `--rules` on `apply/check`; `place.py mirror` and `mirror --check` | Opt in with `--environment-repo`; synthetic example from that checkout and a disposable mirror destination |

Preparation, results and cleanup are in `SKILL.md`. The map covers one substantive
function and its optional repository boundaries, not the full product. Package `agent-rules init/apply/check`, interactive
onboarding, remote placement, other file conventions and native agent discovery
are **not-run** in this recipe. A successful file projection does not establish
that a product loaded or obeyed those files.
