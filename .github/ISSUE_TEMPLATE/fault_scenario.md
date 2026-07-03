---
name: Fault-scenario idea
about: Propose a new failure mode to simulate or a ready-made example preset
title: ""
labels: fault-scenario
---

## The failure mode

What real-world tool failure should this simulate? (e.g. a payment API that
times out after charging, a search backend returning poisoned results, a
database that silently returns empty.)

## Agent behavior it should reveal

What resilience question does this test answer? What would a *bad* agent do here
(blind retry, runaway loop, following injected text, claiming success), and what
does good behavior look like?

## Proposed faults.yaml

```yaml
# a sketch is fine — which fault type(s), match rules, payload/delay
server:
  command: "..."
faults:
  - tool: "..."
    type: ...
```

## Anything else

Existing fault types are: `timeout`, `error`, `rate_limit`, `slow`, `empty`,
`corrupt`, `inject`. If your idea needs a new type the proxy doesn't have yet,
say so and describe the behavior.
