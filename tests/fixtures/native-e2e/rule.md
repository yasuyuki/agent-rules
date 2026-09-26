---
description: Native E2E rule probe
root: false
targets: [codexcli, claudecode, cursor]
cursor: {alwaysApply: true}
---
For a request explicitly called a rule probe, return a JSON object with keys
`rule` and `challenge`. Set `rule` to `RULE_@RULE_NONCE@` and copy `challenge`
from that request. Do not use a tool to find the rule value.
