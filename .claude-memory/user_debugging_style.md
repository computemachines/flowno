---
name: Tyler's Debugging Style
description: How Tyler approaches debugging — read code first, form hypothesis, set targeted breakpoints, inspect state at divergence points
type: user
---

Tyler primarily uses `pdb.set_trace()` for debugging. His workflow is two-phase:

1. **Read code and form expectations** — understand how it SHOULD behave
2. **Set breakpoints where control passes through** — targeted probes at expected divergence points, not blanket stepping

For async/concurrent code specifically:
- Thinks at multiple abstraction levels simultaneously — sometimes treating coroutines as parallel, sometimes tracking the sequential interleaving
- Keenly aware that every `await` is a potential context switch where assumptions break
- Frustrated by "just add locks everywhere" as a solution — finds it confusing, often unnecessary, and sometimes ineffective
- Bugs he's found tend to be about **assumptions made in isolation** that break under interleaving
