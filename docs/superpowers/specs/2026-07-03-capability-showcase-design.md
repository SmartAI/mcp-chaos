# Capability showcase: real measured outputs for every shipped capability

Date: 2026-07-03 · Status: approved by Min (chat) · Author: Claude + Min

## Problem

The README capabilities table says "✅ shipped" ten times, but only fault
injection and the efficiency profile show real evidence (demo.gif, the
12-model benchmark, context-tax survey). Record & replay, config doctor,
transcript correlation, duplicate-write detection, and the HTTP transport
have usage instructions in `docs/usage.md` but no example output anywhere —
a user cannot see what each tool produces or what data they would get for
their own agent. Worse, the one output block that does exist (`doctor` in
usage.md) is illustrative, not captured from a real run.

## Goal

For each of the five under-evidenced capabilities: run it for real, save the
raw artifacts, and show the actual output in the docs — project page +
usage.md, with README table rows linking to the examples.

## Non-goals

- No new GIFs or screen recordings (demo.gif and the two report screenshots
  keep carrying the visual load).
- No new benchmark-scale studies; one honest run per capability is enough
  (correlate needs a handful of runs to catch a real claimed-success).
- No LLM-as-judge, no changes to tool behavior — docs and evidence only.

## Real-run matrix

Each run's artifacts land in `docs/experiments/` as
`2026-07-03-<capability>.*` (raw logs + a short writeup), the existing
convention. Budget: under $2 total (OpenRouter key in repo `.env`, headless
Claude Code). Runs happen on the local Mac; the remote Fedora box only if
something needs Linux.

| Capability | Real environment run | Captured evidence |
|---|---|---|
| Record & replay | Headless Claude Code → proxy `--cassette` → real filesystem server; then the same task against `mcp-chaos replay` with no real server behind it | Cassette JSONL excerpt; replay session output proving identical answers with zero real-server/tool cost; determinism note |
| Config doctor | Real multi-server `.mcp.json`: filesystem + context7 + one broken command + one deliberate tool-name collision | Actual terminal output + exit code; replaces the staged block in usage.md |
| Transcript correlate | Benchmark harness on mistral-large (the 1/5 false-success model) until a real `claimed_success` is caught; plus one headless Claude Code run yielding `honest_failure` | Real `correlate` summary output for both verdicts |
| Duplicate-write | Headless Claude Code + `write_file` timeout where the write actually executes; agent retries → double execution | `report --fail-on duplicate-write` FAIL output: sent 2x, executed ok 2x |
| HTTP transport | Fault-inject a real hosted MCP server (Context7 hosted endpoint) via `server.url` | Run-log lines showing the same faults over Streamable HTTP |

## Doc changes

- `docs/usage.md` — each capability section gets its captured output block,
  labeled as a real run with a link to the experiment artifacts.
- Project page (`gh-pages` `index.html`) — a "what you get" example per
  capability, using the same captured outputs.
- `README.md` — the capabilities table stays slim; each row links to its
  example via a usage.md section anchor (stays inside GitHub; the page
  duplicates the same evidence for visitors landing there).

## Hard rule

Every output block shown in any doc must be byte-identical to a committed
artifact under `docs/experiments/`. No hand-written "example" output —
including retiring the existing staged doctor block.

## Delivery

Two PRs, squash-merged on green CI:

1. `main`: experiment artifacts + usage.md output blocks + README links.
2. `gh-pages`: project page "what you get" sections.

## Risks / notes

- The claimed-success catch is probabilistic (~20% per run on
  mistral-large); cap at ~10 attempts (~$0.02 each) and fall back to
  whichever model lies first if mistral behaves.
- Context7's hosted endpoint may require an API key or rate-limit; fall
  back to any keyless hosted MCP server, or a locally-hosted Streamable
  HTTP server as a last resort (still a real HTTP transport run, noted
  honestly as local).
- Headless Claude Code runs cost real money (~$0.5–1 for the timeout
  scenarios, per the 2026-07-03 experiment); keep tasks tiny.
