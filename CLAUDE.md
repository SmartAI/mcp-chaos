# mcp-chaos — project context

## What it is

A transparent MCP proxy that injects faults into any agent's tool calls to test
resilience. One line: Chaos Monkey for AI agents, at the MCP layer. The
differentiation is **protocol layer + zero code**: change one line of MCP config
to insert the proxy; works with every MCP client.

## Engineering principles

- KISS. No abstraction we don't need yet.
- MVP judging is deterministic (retry count, loop detection, claimed-success vs
  actual-tool-failure). LLM-as-judge is a later, optional add-on.
- Single-command experience first: `uvx mcp-chaos run ...` should just work.

## Known scope boundary (be honest about this)

The proxy sees MCP tool traffic, not the agent's natural-language output. So it can
directly observe retries, loops, and give-up behavior. Detecting "the agent claimed
success while the tool failed" needs transcript correlation (e.g. Claude Code
session jsonl) — that's a roadmap item, not MVP.

## MVP scope

Do: stdio MCP transparent proxy, YAML fault config (7 fault types, match by tool
name / call count / probability), event recording, single-file HTML report.
Don't: LLM-layer faults, cloud service, CI plugin, fuzzing, multi-language SDK.

## Validation status

Verified against a real agent on 2026-07-03: a single injected `write_file`
timeout against headless Claude Code + the official filesystem server produced
4 blind retries and ~$1 burned per run, with the full event log captured. See
docs/experiments/2026-07-03-claude-code-timeout.md. The design was also checked
against the MCP 2026-07-28 release candidate (stateless changes target
Streamable HTTP; the pass-through stdio relay is unaffected).

## Internal notes

Strategy and research notes live in `private/` (gitignored, local only). Never
commit or push anything under `private/`, and never push the local
`private-history` branch.
