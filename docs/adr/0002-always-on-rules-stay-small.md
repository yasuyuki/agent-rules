# Keep always-on rules small; conditional procedures are skills

Every rule in `rules/` is loaded into every agent session, and the set grew from 14.5 KB (2026-08-23) to 35.0 KB (2026-10-12) as incident fixes were appended. A rule now holds only invariants that apply to most sessions. Procedures that only some work reaches (topic sync, handover and retirement; phase documents; rule experiments; documentation and public-tool authoring) are project skills loaded by their description, and the remaining rule names the skill where the condition arises.

The `handoff` rule is removed rather than kept as a stable identifier, superseding that part of ADR 0001: workspace HANDOFF files are retired, and resumption in the owning task Issue or work record is stated where it is used. Consumers drop it on their next export.
