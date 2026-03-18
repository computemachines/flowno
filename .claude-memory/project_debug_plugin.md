---
name: Claude Debug Plugin — Design Ideas
description: MCP debugger for Flowno's event loop + trace-based debugging architecture + stack trace rewriting
type: project
---

## Goal

Build debugging tools for Flowno's custom event loop. Branch: `claude-debug-plugin`. Two related efforts:

1. **MCP debug server** — interactive inspection of event loop state (suspended tasks, frames, locals, generation tracking, stream consumer state)
2. **Stack trace rewriting** — rewrite tracebacks for spawned coroutines to include spawn-site stack, like asyncio does for Tasks

## How Programmers Actually Debug (insights from discussion)

**Phase 1 — Narrowing the search space:** Before any breakpoint, mentally partition code into "trusted" and "suspect" regions. Don't step through known-good primitives (Lock, Condition). Focus on flow-level decisions.

**Phase 2 — Defining "surprising":** Have a mental model of what SHOULD happen. Debug session is about finding where reality diverges from that model. Check assertions at key points, not inspect everything.

**Phase 3 — Causal reasoning backwards:** When divergence found, ask "how did it get into this state?" Look at history: who last modified this value, what event caused this task to wake up.

**Phase 4 — Maintaining invariants (unconscious):** Track simplified key invariants like "Source should only run once in acyclic graph", "barrier1 count should equal unread consumers". When one breaks, that's the bug.

**Phase 5 — Abstraction level switching:** Fluidly move between graph level ("Source feeds two Forks"), generation level ("Source is at (0,)"), and event loop level ("this task yielded WaitForStartNextGenerationCommand").

## Evolved Design Direction (2026-03-18)

Key realization: a GDB-style interactive debugger is wrong for LLMs — expensive repeated context for trivial decisions. Instead:

**The system is a story-teller, not a fixer.** It presents narratives about a problem. What you do with the information is separate.

### Architecture

1. **Recorder** — runs the program, captures full state at every line/tick. Produces a trace database: `(tick, frame, file, line, variable, value)`. For event loop: also task switches, generation changes, stream buffer state. Optimizations: pre-pruning, diff compression, configurable granularity.

2. **Discrepancy input** — user provides "expected X, got Y" as starting point. Knowing the expected value tells the system what to pay attention to.

3. **Chain builder** — walks backward through trace using a small model to prune data dependencies. At each step: mechanical trace (what assignment produced this value?) + pruning (which input is responsible for the discrepancy?). Needs ~4B+ param model for reversing functions.

4. **Presenter** — renders causal chain as a narrative story connecting the surprise to its origin.

### Query Model

Generic queries on trace database (no model needed):
- "When did X change?" — scan for mutations
- "What was state at tick N?" — direct lookup
- "Between ticks A and B, what changed?" — diff
- "What depends on X after tick N?" — forward scan (blast radius)
- "Compare these two intervals" — diff two invocations of same function

These are filter, diff, and slice operations. Each reduces thousands of ticks to a handful of facts.

## Async-Specific Debugging Challenges

- At some abstraction levels, treat coroutines as parallel. At others, must be aware of sequential nature and how execution jumps through the event loop.
- Every `await` / `yield` is a potential context switch. Assumptions made in isolation break when other tasks interleave.
- Bugs exist specifically BECAUSE of async — they wouldn't exist in non-streaming/non-async execution.

## Prototype Work Done

- `inspection/trace_simple.py` — Uses `EventLoopInstrument` hooks to log every send/throw cycle
- `inspection/probe_simple.py` — Uses `sys.settrace` to pause at a specific line, then inspects locals, call stack, and all suspended task frames
- `inspection/simple.py` — Simplified to plain synchronous Python for reasoning about minimal debugger views
- `inspection/DESIGN.md` — Full design doc captured in repo

## PlusCal Route (alternative/complementary)

TLA+/PlusCal formal verification is a last resort. Infrastructure exists in `formal-verification/`. Could complement runtime debugging but is expensive to write specs.

**Why:** The streaming fork/join bug is too subtle to solve by code inspection or logging alone (10,000+ lines of relevant output). Need better tools.

**How to apply:** Focus on trace-based tooling first. Minimize modifications to the library itself — only event loop introspection hooks should need clean interfaces.
