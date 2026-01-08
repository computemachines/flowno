# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Test Commands

```bash
# Run all tests (10 second timeout per test)
uv run pytest -v

# Run a single test file
uv run pytest tests/test_streaming.py -v

# Run a single test by name
uv run pytest -k "test_stream_cancellation" -v

# Build documentation
cd docs && make html
```

## Important Context

**This is NOT asyncio.** Flowno has its own custom event loop implementation at `src/flowno/core/event_loop/`. Do not use `import asyncio` or asyncio primitives. Use Flowno's equivalents:
- `flowno.sleep()` instead of `asyncio.sleep()`
- `flowno.spawn()` instead of `asyncio.create_task()`
- `flowno.AsyncQueue` instead of `asyncio.Queue`
- `flowno.Event`, `flowno.Lock`, `flowno.Condition` for synchronization

## Architecture Overview

Flowno is a dataflow DSL with three layers:

### 1. Event Loop (`src/flowno/core/event_loop/`)
A standalone cooperative multitasking system using command-based coroutines. Coroutines yield `Command` objects to the event loop which handles them and resumes the coroutine.

Key files:
- `event_loop.py` - Core scheduler, task management, socket/timer handling
- `commands.py` - Command types yielded by coroutines (Sleep, Spawn, Join, etc.)
- `queues.py` - `AsyncQueue` and `AsyncSetQueue` implementations
- `synchronization.py` - Event, Lock, Condition primitives

### 2. Flow Runtime (`src/flowno/core/flow/`)
Builds on the event loop to execute dataflow graphs with dependency resolution, cycle breaking, and streaming.

- `flow.py` - `Flow` class: main execution engine. Schedules nodes when inputs are ready, manages generations for cycles
- Nodes progress through generations (tracked as tuples like `(0,)`, `(0, 1)`) for cycle support

### 3. Node System (`src/flowno/core/` and `src/flowno/decorators/`)
- `node_base.py` - `DraftNode`/`FinalizedNode` base classes, `Stream` type for streaming data
- `mono_node.py` - Nodes that return a single value
- `streaming_node.py` - Nodes that yield multiple values via `AsyncGenerator`
- `group_node.py` - Composite nodes (subgraphs)
- `decorators/node.py` - The `@node` decorator that transforms async functions into node factories

### FlowHDL (`src/flowno/core/flow_hdl.py`)
The declarative context manager for defining graphs:
```python
with FlowHDL() as f:
    f.a = Node1()
    f.b = Node2(f.a)  # backward reference
    f.c = Node3(f.d)  # forward reference (resolved at context exit)
    f.d = Node4(f.c)  # creates a cycle
```
Forward references work via `__getattr__` returning placeholder objects.

## Key Concepts

**Generations**: Cycles require "default values" to bootstrap. Each cycle iteration increments the generation. Generation tuples like `(0, 1, 2)` track nested cycle depth.

**Streaming**: Nodes can yield values incrementally. Consumers receive a `Stream` object and iterate with `async for`. Cancellation propagates upstream via `StreamCancelled` exception.

**Run Levels**: Cycles have "run levels" determining which generation's output to use for a given input.

## Formal Verification (TLA+/PlusCal)

The `formal-verification/` directory contains TLA+ specs for model checking.

```bash
# Transpile PlusCal to TLA+
java -cp formal-verification/tla2tools.jar pcal.trans ./formal-verification/specs/models/YourSpec.tla

# Run TLC model checker
java -cp formal-verification/tla2tools.jar:formal-verification/specs/modules:formal-verification/specs/models \
  tlc2.TLC -config formal-verification/specs/model-tests/Config.cfg \
  formal-verification/specs/models/Model.tla
```

Do NOT use MCP servers for TLA+/PlusCal work - use command line tools.

## Naming Conventions

Node names are capitalized (e.g., `Add`, `Print`) because they are factory functions that return `DraftNode` instances, similar to class constructors.
