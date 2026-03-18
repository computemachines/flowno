---
name: Claude Debug Plugin — Design Ideas
description: Ideas for an MCP debugger specialized for Flowno's custom event loop, from the 2026-03-17 exploration session
type: project
---

## Goal

Build an MCP server that gives Claude interactive debugging capabilities for Flowno's custom event loop. Branch: `claude-debug-plugin`.

## How Programmers Actually Debug (insights from discussion)

**Phase 1 — Narrowing the search space:** Before any breakpoint, mentally partition code into "trusted" and "suspect" regions. Don't step through known-good primitives (Lock, Condition). Focus on flow-level decisions.

**Phase 2 — Defining "surprising":** Have a mental model of what SHOULD happen. Debug session is about finding where reality diverges from that model. Check assertions at key points, not inspect everything.

**Phase 3 — Causal reasoning backwards:** When divergence found, ask "how did it get into this state?" Look at history: who last modified this value, what event caused this task to wake up.

**Phase 4 — Maintaining invariants (unconscious):** Track simplified key invariants like "Source should only run once in acyclic graph", "barrier1 count should equal unread consumers". When one breaks, that's the bug.

**Phase 5 — Abstraction level switching:** Fluidly move between graph level ("Source feeds two Forks"), generation level ("Source is at (0,)"), and event loop level ("this task yielded WaitForStartNextGenerationCommand").

## Async-Specific Debugging Challenges

- At some abstraction levels, treat coroutines as parallel. At others, must be aware of sequential nature and how execution jumps through the event loop.
- Every `await` / `yield` is a potential context switch. Assumptions made in isolation break when other tasks interleave.
- The typical solution (locks/mutexes everywhere) is confusing, often unnecessary, and sometimes doesn't fix the problem.
- Bugs exist specifically BECAUSE of async — they wouldn't exist in non-streaming/non-async execution.

## Debugger Architecture Ideas

### Event-loop-native tracing
Instead of generic line-by-line debugging, trace at the event loop's natural granularity: each `task.send()` / `task.throw()` cycle. Show which task ran, what Command it yielded, what happened next.

### Interleaving timeline
A numbered log of atomic steps showing the global scheduling order:
```
[1] Source#0: push_data((0,), rl=1) → gen=(0,0)
[2] Source#0: barrier1.set_count(2)  [Fork#0, Fork#1]
[3] Source#0: YIELD barrier1.wait()
[4] Fork#0: StreamCheck → Some(0)
[5] Fork#0: barrier1.countdown(Source) → count=1
```

### Suspended task inspection
When paused at a point, inspect ALL suspended coroutines via `.gi_frame` / `.cr_frame` — see their locals, where they're suspended, and what they're waiting for. Prototype working in `inspection/probe_simple.py`.

### Key state at any pause point
- Table of all nodes: current status + generation
- Resolution queue contents
- Barrier counts on each node
- Which node is currently executing and what it just yielded
- Stream consumer states

### Breakpoint types
- Line breakpoints (via `sys.settrace`)
- Conditional breakpoints on command type or task state
- "Break when node X gets resumed for generation > Y"
- Break on invariant violation

## Prototype Work Done

- `inspection/trace_simple.py` — Uses `EventLoopInstrument` hooks to log every send/throw cycle
- `inspection/probe_simple.py` — Uses `sys.settrace` to pause at a specific line, then inspects locals, call stack, and all suspended task frames from the event loop
- Both work against the bare event loop (not the Flow layer), which is the right scope for initial development

## PlusCal Route (alternative/complementary)

Translating actual flow execution into a PlusCal spec for TLC model checking could exhaustively verify deadlock freedom and invariants. Formal verification infrastructure already exists in `formal-verification/`. Could complement runtime debugging.

**Why:** The root cause is that stale check `<=` vs `<` at `node_base.py:648` — equal generations treated as stale causes spurious re-execution. A formal spec could have caught this.

**How to apply:** Consider both runtime debugging (MCP tool) and static verification (PlusCal) as complementary attack vectors for concurrency bugs.
