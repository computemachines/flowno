# Debug Tooling Design Notes

## Goal

Build an automated dashboard into a codebase that presents **stories about a problem**. Not an auto-fixer. The system makes the invisible visible — what you do with that information is a separate problem.

## Why Not a Traditional Debugger?

A GDB-style interface is optimized for human eyes that scan cheaply. For an LLM, repeated context (mostly-identical state dumps) is expensive and wasteful. And the actual decisions ("step into? step over?") are trivial compared to the cost of reading the state.

Interactive debugging also doesn't work well because:
- Every step sends large uncacheable blocks of mostly-similar text
- The decision at each step ("advance") uses almost none of the LLM's capability
- If raw interactive debugging were effective for LLMs, it would be done more often

## Key Insight: Observation vs. Mutation

In an interpreted language where you can observe everything externally, the real value of a debugger is **mutation** — testing counterfactuals. A human steps through to build a mental model, then changes a variable or function to test a hypothesis.

LLMs already do a version of this: add logging, guess the problem, edit source, observe changes. But this breaks down when:
- Log output is massive (10,000+ lines of relevant data)
- Multiple concurrent tasks with novel algorithms
- Subtle interactions that require holding many facts simultaneously

## Architecture

### 1. Recorder

Run the program, capture full state at every line (or configurable granularity). Store as a trace database: `(tick, frame, file, line, variable, value)` tuples.

For cooperative multitasking (like Flowno's event loop), also capture: which task is active, what other tasks exist and their suspended state.

Optimizations for large programs:
- Pre-pruning: ignore variables not mentioned in queries
- Compression: only store diffs between ticks
- Configurable granularity: every line, every function entry/exit, or breakpoint-only

### 2. Discrepancy Input

The user provides the starting point: **"expected X, got Y."**

This is not "why did this happen?" — it's a concrete discrepancy. Example: "expected `message: 1` in stdout, got `message: 2`."

Knowing the expected value tells the system what to pay attention to. We don't care about `print`'s return value or the string literal `"message: "` — the discrepancy is in the `1` vs `2`.

### 3. Chain Builder

Walk backward through the trace from the discrepancy, building a causal chain.

At each step, two operations:

1. **Mechanical trace** (cheap, no model): What assignment produced this value? What were the inputs to that expression?

2. **Pruning** (small model): Which input is responsible for the discrepancy? Example: `str(thing)` produced `"2"` but expected `"1"` — is the problem `str` or `thing`? Since `str` is a builtin, almost certainly `thing`. If it were `my_custom_serializer(thing)`, might need to explore both branches.

The model's job is narrower than reversing functions. It answers: "given this discrepancy, which branch of the data dependency is more likely responsible?" That's a confidence judgment, not a computation. Probably needs a 4B+ parameter model at minimum.

The chain terminates when we reach something the user recognizes as the root cause — an assignment, a condition, a function call that explains the unexpected value.

### 4. Presenter

Render the chain as a narrative story:

> "At line 12, `thing` changed from 1 to 2 because of `thing + 1`. This flowed into `str(thing)` at line 13, which became the `message` parameter of `my_sleeper`, which produced the output you didn't expect."

Not a wall of state dumps. A directed story that connects the surprise to its origin.

## Query Model

Follow-up queries depend on earlier queries. The system builds up context as the user refines their understanding.

Generic queries on the trace database (no model needed):
- **"When did X change?"** — scan for mutations of variable X, return ticks
- **"What was the state at tick N?"** — direct lookup
- **"Between ticks A and B, what changed?"** — diff
- **"What depends on X after tick N?"** — forward scan for reads of X (blast radius of a hypothetical change)
- **"Compare these two intervals"** — diff two invocations of the same function

These are filter, diff, and slice operations on a table. Each one reduces thousands of ticks down to a handful of facts.

## Applying to Flowno's Event Loop

The recorder hooks into `EventLoopInstrument` to capture task-level events alongside frame/locals data. The trace naturally includes:
- Task switches (which coroutine the event loop sent to)
- Generation tuples at each scheduling decision
- Stream buffer state (what values are pending for which consumers)

Stories would involve concurrency: "Task A was suspended here, Task B ran and changed this shared state, then Task A resumed with stale generation data."

The fork/join bug would be approachable as: "expected Join to receive [0,1,2] from both forks, but fork0b's stream was [truncated/wrong]. Trace back to when fork0b's stream diverged from fork0a's."

## Open Questions

- How to handle the "reversing" problem when the model needs to translate a discrepancy through a function call (e.g., `str(thing)="2"` expected `"1"` → `thing=2` expected `1`). Simple for builtins, harder for user functions.
- When does the chain builder give up and say "I need a finer-grained trace in this region"?
- How to present concurrent causal chains where the cause involves interleaving of multiple tasks?
- What's the right storage format for the trace database? Needs to support both sequential scans and point queries efficiently.
- The system can estimate blast radius of a proposed change within the recorded execution, but can't predict behavior of a different execution. At some point you re-run and check.
