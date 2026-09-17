---
name: classify-work
description: Classify unfinished work by phase and propose suitable registered environments, separating technical requirements from readiness and preserving execution boundaries. Use for work triage or environment routing, not to execute the classified work.
---

# Classify work

Resolve the environment catalog and public `place.py` from the workspace's
explicit environment binding. Read the public README's work-classification
schema before preparing input. Do not discover an authority by searching other
HOME directories or silently choose another catalog.

Reconcile the request with the current handoff, open issue ledger, and relevant
product acceptance records. Keep references and classification conditions in
the work input, not a second progress ledger. Exclude completed items and record
why other apparent work is outside the request. An old phase file alone does
not establish current scope. Ask only for material conditions the records do
not resolve; otherwise preserve the uncertainty.

Split work where execution requirements or acceptance evidence change: source
editing and synthetic tests can differ from target-OS tests, GUI/device use,
trusted deployment, and actual experiment execution. For each phase identify:

- OS, tools, GUI, devices and compute requirements;
- source/data/credential/key access and connections, including host assets that
  could be affected;
- purpose, executor and existing approval or sealed-authority boundaries;
- approval/sandbox mode, interoperability requirements, acceptance risk, and
  explicit exclusions or prohibited operations, each as distinct capability
  requirements where the catalog can evidence them;
- evidence needed for acceptance and the existing route for handing over
  source, artifacts and results.

Prefer isolation when requirements are met. Consider whether dependencies can
be reproduced and the phase can be moved or recovered without exposing host
assets. A missing tool is not an isolation prohibition: mark it preparable only
when an existing authorized preparation route is supported by evidence.
Otherwise leave it unknown. Never assume credentials can be copied.  Purpose,
active state, OS family, and a physical distro identify neither the logical
runtime principal nor approval, sandbox, interoperability, or risk acceptance.
Do not propose a contract-changing preparation, such as adapting an isolated
permissive-approval environment for non-permissive Windows interoperation.

Run the read-only `place.py classify --catalog … --work …
--prefer-environment …` entry point, using `--json` for structured reuse. A
capability declaration is evidence for a proposed route, not proof of current
remote reachability or permission to execute. Preserve purpose and lifecycle
rules: pending environments are for construction/repair; retained environments
need explicit selection; retired/unclassified environments are not candidates.

Present per-phase classifications, candidates, reasons, preparation and missing
conditions. Separately show holds, natural-event waits and missing executor
assignment. Distinguish CI, another environment's agent and human operations.
Keep the selected environment's concrete identity and logical runtime principal
separate from its physical host/distro; preserve retained records rather than
collapsing same-distro principals.  For a cross-environment handoff, the work
record or recipient text must stand alone with the actual environment, logical
ID/principal, existing entry point, requested mode, acceptance risk, material
exclusions/prohibitions, cited capability evidence, and every unknown condition.
If phases use different environments, explain the handover using existing
transfer paths; unknown transfer paths remain unresolved. Identify the accessible
shared task and required recipient notification as proposed handoff steps. When
an applicable `handoff` rule is available, use it to describe those steps; do not
perform them as part of classification. Classification output alone is not
delivery or receipt.
Do not substitute synthetic success for real acceptance.

Classification does not authorize launching agents, installing tools,
connecting to hosts, transferring data, releasing artifacts or starting
experiments. Update capability evidence only from observed facts or cited
records, and use the existing inventory and skill placement mechanisms.
