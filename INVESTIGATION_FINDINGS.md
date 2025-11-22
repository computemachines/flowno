# Concurrency Timeout Investigation Findings

## Issue
Test `test_stream_multiple_chunks_delayed_consumption` times out after 5 seconds due to an infinite loop.

## Root Cause Analysis

### The Problem Sequence

1. **AsyncGenerator completes**: ThreeChunkSource yields 3 chunks ('alpha', 'beta', 'gamma') and completes
2. **Final data pushed**: The generator pushes final run_level 0 data at generation (1,)
3. **Output nodes enqueued**: Consumer1 and Consumer2 are added to the resolution queue
4. **Node waits**: ThreeChunkSource yields `WaitForStartNextGenerationCommand` and waits at generation (1,)
5. **Consumer re-executes**: Consumer1 is popped from the queue and restarts its coroutine
6. **Consumer requests data**: Consumer1 tries to read from the stream starting fresh
7. **Producer re-executes**: Consumer1's stall request wakes up ThreeChunkSource
8. **ThreeChunkSource restarts**: Starts yielding from the beginning at generation (1, 0)
9. **Infinite loop**: Process repeats indefinitely

### The Core Issue

Nodes in Flowno are designed to run in an infinite loop (`while True` in `evaluate_node`), re-executing after each generation. The termination mechanism relies on:
1. All nodes reaching "Ready" state (waiting for next generation)
2. Resolution queue being empty
3. When both conditions are met, the queue closes and execution terminates

**The race condition**: Output nodes are enqueued AFTER async generators complete but BEFORE the termination check can properly evaluate. By the time all nodes are "Ready", the resolution queue already contains nodes that will trigger re-execution.

### Why the Timing Matters

```
GOOD CASE (test passes):
- Source yields 1 chunk
- Consumers consume it
- Source completes at (0,), outputs enqueued
- ALL consumers detect parent gen changed from (0,) to ()
- All nodes become Ready simultaneously
- Queue empties
- Termination check succeeds
- Flow closes

BAD CASE (test fails):
- Source yields 3 chunks with delays
- Consumer1 finishes first, yields WaitForStartNextGenerationCommand
- Consumer1 is marked Ready, waiting
- Consumer2 still running
- Source completes, enqueues Consumer1 and Consumer2
- Consumer1 already in queue from earlier
- Consumer2 completes, marked Ready
- Now all nodes Ready, BUT queue has Consumer1
- Termination check: queue not empty, so don't close
- Consumer1 popped from queue
- Consumer1 re-executes
- Requests data, wakes up Source
- Source re-executes
- INFINITE LOOP
```

## Attempted Fix

Added `await self._enqueue_output_nodes(node)` immediately after pushing final run_level 0 data in async generator completion handlers (lines 558 and 589 in flow.py).

**Result**: Did not solve the issue. The timing problem persists because:
- Output nodes are enqueued whether it's done early or late
- The termination check still happens at the wrong time
- AsyncSetQueue prevents duplicate enqueueing but doesn't prevent the race

## The Real Solution (Not Implemented)

The proper fix requires one of these approaches:

1. **Add node completion tracking**: Mark nodes as "Completed" when they finish, and prevent re-execution of completed nodes
2. **Fix termination check timing**: Move the check to happen before processing queue items, or synchronize it better
3. **Prevent enqueueing after completion**: Don't enqueue output nodes when a node has completed its final execution
4. **Close queue proactively**: When an async generator completes, check if all downstream consumers have also completed, and close the queue if so

Each approach requires significant refactoring of the node lifecycle and termination logic.

## Files Modified

- `src/flowno/core/flow/flow.py`: Added early output node enqueueing (partial fix)
- `test_debug_concurrency.py`: Created minimal reproduction test

## Recommendations

1. The termination logic in `WaitForStartNextGenerationCommand` handler (lines 1094-1100) needs to be more sophisticated
2. Consider adding a "Completed" state to `NodeTaskStatus` to track finished nodes
3. Add synchronization between async generator completion and termination checks
4. Review the overall node lifecycle management for streaming nodes

## Time Spent

- Installed pytest-timeout
- Ran tests and identified failing test
- Enabled comprehensive debug logging
- Compared passing vs failing traces
- Traced execution through ~10 files and 1000+ lines of code
- Identified root cause after analyzing node lifecycle, generation management, and queue handling
- Attempted partial fix (unsuccessful)

The issue is complex and involves subtle race conditions in the async event loop, generation management, and node scheduling system.
