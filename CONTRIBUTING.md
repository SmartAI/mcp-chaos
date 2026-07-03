# Contributing to mcp-chaos

Thanks for helping test agent resilience at the MCP layer. This is a small,
pre-alpha project moving fast — contributions are welcome, and this guide keeps
them easy to land.

## Dev setup

```bash
git clone https://github.com/SmartAI/mcp-chaos && cd mcp-chaos
uv sync                              # install the project into a local venv
uv run --with pytest pytest -q       # run the test suite
```

`uv run --with pytest` pulls pytest in on demand so you don't need it installed
globally. (A dedicated dev dependency group may be landing separately; once it
does, `uv sync --group dev` + `uv run pytest -q` will be the shorter path.)

## Project principles

Read `CLAUDE.md` for the full project context. The short version that shapes
what gets merged:

- **KISS.** No abstraction we don't need yet. Prefer a few clear lines over a
  framework.
- **Deterministic checks over LLM judging.** The MVP judges resilience from
  observable facts (retry counts, loop detection, tool-failure vs claimed
  success). LLM-as-judge is a later, optional add-on — not the first tool we
  reach for.
- **Single-command UX first.** `uvx mcp-chaos run ...` should just work. Keep the
  happy path one command, one config file, zero code changes to the agent.

Also honest about scope: the proxy sees MCP tool traffic, not the agent's
natural-language output. Features that need transcript correlation are roadmap,
not MVP.

## What's most wanted

- **Fault-scenario ideas.** New failure modes worth simulating, or ready-made
  `examples/*.yaml` presets. See the existing ones in `examples/` for the style.
- **MCP-client compatibility reports.** Did the proxy work (or not) with a client
  we haven't tried — a specific IDE, a custom agent, another language's MCP SDK?
  Tell us what you saw.
- **Experiment replications.** Re-run the experiments in `docs/experiments/`
  against other agents/models and share the numbers. N=1 results need company.

## Before you start something big

For anything beyond a small fix or a new example, **open an issue first** so we
can agree on scope before you write code. It saves everyone a rewrite. Use the
issue templates — there's one for bug reports and one for proposing a new fault
scenario.
