---
name: necessity-for-docs-and-tools
description: Necessity rules for documentation and public artifacts. Use when creating or changing a README, manual, agent instruction, rule or skill, or a public tool or public skill.
---

# Necessity for docs and tools

Applies the always-on `msw-necessity` rule to documents and public artifacts.

## Single source of truth

Keep one editing source for each piece of information. Agent-facing durable
documents hold only purpose, judgement and external contracts that code or
help cannot provide; code owns behaviour, arguments, defaults and input
constraints, so improve help or a nearby comment when needed. Moving text to
another document is not a reduction. Keep an execution contract's purpose,
permissions and acceptance.

Other documents are short indexes to a retrievable source, and generated
distributions are mechanically identical copies. A human manual may keep
purpose-oriented explanations, but an argument list is never a second
handwritten source. Keep the target, conditions and success criteria; a README
holds the purpose, the shortest way to start and the entry to the manual.

## Before editing

Use `optimize-human-docs` for human-facing text and `optimize-agent-docs` for
agent-facing text, each on its own part of a mixed document, when those skills
are available. When code or help changes, review the related explanations,
skills and rules in the existing review and remove procedures that became
unnecessary in the same change. A document whose content needs no change gets
no formal update.

## Public tools and skills

A public tool takes environment differences through explicit configuration,
with private execution code and machine-specific values left out of its
required dependencies. A public skill stays small and usable on its own; a
specific repo, private settings, a model, an MCP server or a dedicated CLI is
never a runtime requirement. Accept changes to startup, configuration or
dependencies using only public code plus a separately placed synthetic
configuration. Success in the owner's environment or in wrapper-only tests does
not prove independence.
