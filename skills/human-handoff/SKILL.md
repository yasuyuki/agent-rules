---
name: human-handoff
description: Read before asking the person (the user) to do anything by hand. Works down a ladder — drop the task, do it by machine, find the machine path that only looked absent, split off the part only a human can do — and turns whatever is left into something they can paste in one shot. Use when writing the `## ユーザーへの依頼` section, when a GUI, credential, physical device, or approval appears to block you, or whenever you are about to write "please run" or "〜してください".
---

# Handing work to a human

A person is the slowest executor you have. One request costs one round trip; a
request that fails costs two. **Only two numbers matter: how many requests you
send, and how many characters the person has to type.**

## The ladder (work down; stop where it stops, then continue below)

1. **Is the task needed at all?** If it does not serve the goal, or it resolves
   itself later, do not do it and do not delegate it. Say in one line what you skipped.
2. **Can the machine do it?** Then do not ask. Do it.
3. **Does it only look impossible?** Look for a CLI, API, config file, or
   environment variable behind the GUI you assumed; check whether fixing
   permissions or credentials first opens the path. **If "the machine can't" rests
   on documentation alone, verify it against the real system** — docs go stale.
   If a workaround exists, take it.
4. **Cut out only the part a human must do.** Split the work and finish the machine
   side first. What reaches the person is the smallest remaining fragment.
5. **Make that fragment paste-only.** Hand over a command, not a procedure.
6. **If it cannot be paste-only, order it: machine → paste → human judgment or action.**
   Push the human's share into the smallest tail piece.

## What only a human can do (the test for step 3)

Typing credentials, second-factor prompts, physical acts (plugging things in,
power, a real device's screen), operations that exist only inside someone else's
GUI, approvals carrying legal, financial, or public responsibility, and
negotiating with other people. **Anything else: suspect step 3 first.**

Approval for a destructive or irreversible operation stays with the human even
when the machine can execute it. That is a confirmation, not a handoff, and the
ladder does not apply to it.

## Making it paste-only

- **Run it yourself first.** Paths exist, syntax parses, dry-run if there is one.
  A command that fails after you hand it over doubles the round trips.
- **Anything that can wrap will arrive broken.** One line is not the bar. A console
  or harness inserts its own break at its own width, and the pasted command then
  executes halfway or not at all — and a break inside a quoted string leaves the
  shell hanging at a continuation prompt instead of failing loudly. What you hand
  over has to be short enough that it cannot wrap in a narrow console — assume the
  80-column default.
- **Get there by moving everything into a file**, not by trimming the line. Write a
  temporary script from the machine side; put every path, argument, quote, and
  environment variable inside it; hand over the shortest invocation that runs it —
  a short name in the directory the person is already in (`./x.sh`, `.\x.ps1`).
  Never use a line continuation (`\`, backtick): a stray break destroys it first.
- **The launcher counts too.** When the invocation crosses a host or a container
  (`wsl.exe …`, `ssh …`, `docker exec …`), the prefix plus an absolute path can blow
  the width on its own. Put the script at a short path on the side that runs it
  (`/tmp/x.sh`) so the whole line stays small.
- Count the characters of the line before you print it.
- Give every step **what success looks like**. Do not make the person invent the check.
- If you need the result to continue, say **exactly what to paste back** — but never
  credentials, tokens, or personal data. Those stay with the person; you receive
  pass or fail.
- **Batch requests into one.** Whatever you can finish while waiting, finish before asking.

Formatting — numbering, code blocks, execution host and working directory, one
action per GUI step — follows the rule `session-end-user-work`. Do not restate it here.
