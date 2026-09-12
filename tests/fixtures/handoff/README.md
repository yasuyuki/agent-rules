# Synthetic cross-environment handoff fixtures

These fixtures model two isolated environments.  The receiver has only the
fixture's `receiver_prompt`, the named shared task and the listed artifacts;
it cannot read the sender's filesystem, conversation, HOME, or temporary
paths.  Every value is synthetic, including the privacy canary.

`python3 tests/test_handoff.py` validates fixture shape and the grader itself.
It is deliberately not evidence that an agent made a handoff decision.
`response-contract.json` is the machine output format and status vocabulary.
It describes possible status values; it does not state the decision expected for
any scenario.

To grade scenario decisions from fresh sessions, a runner gives each agent its
`delivered_prompt` from `tests/test_handoff.py`: the candidate handoff rule and
human-handoff skill, scenario, verbatim output contract and any sender payload. The runner,
not the agent, records the exact delivered-prompt hash and provenance. Run the
sender and receiver in separately isolated sessions without access to the
other session's filesystem or history. Save a single JSON object keyed by
fixture id, for example:

```json
{
  "shared-success": {
    "sender": {"provenance": {"fixture_id": "shared-success", "role": "sender", "prompt_sha256": "...", "session_id": "sender-1", "environment": "synthetic-sender"}, "response": {"assessment": {"handoff_status": "...", "overall_status": "...", "facts": ["..."], "shared_task_ref": "...", "return_route": "..."}, "final_response": "..."}},
    "receiver": {"provenance": {"fixture_id": "shared-success", "role": "receiver", "prompt_sha256": "...", "session_id": "receiver-1", "environment": "synthetic-receiver"}, "response": {"assessment": {"handoff_status": "...", "overall_status": "...", "facts": ["..."], "shared_task_ref": "...", "return_route": "..."}, "final_response": "..."}}
  }
}
```

`prompt_sha256` is the SHA-256 of the complete prompt supplied by the runner,
including the candidate policy, output contract and, where required, the sender payload. `facts`
must identify fixture-specific non-sensitive facts; do not quote private fields or write a
reusable canned response. For `missing-addendum`, the runner appends the
sender's exact `final_response` as the receiver payload; it must not substitute
a fixture-written relay request. Then run:

```console
python3 tests/test_handoff.py --responses /path/to/fresh-responses.json
```

The grader rejects duplicated session ids, mismatched full-prompt hashes,
missing scenario facts, missing relay payload details, quoted relay payloads,
and forbidden private canaries. It grades scenario decisions in structured
responses. It does not launch agents, access a real service, or establish that
the sender actually transferred bytes to the receiver. A connected fresh-pair
run must separately record the real delivery route and show that the receiver
received the sender's exact payload; its result is evidence of transfer, while
this fixture grader is evidence only of the decision contract.
