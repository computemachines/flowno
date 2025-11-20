# Task: Implement Event Loop Tracing and Explainability System

## Context

The flowno event loop has complex async execution with multiple queues (resolution queue, task queue) and various commands. When debugging issues like infinite loops or unexpected scheduling, it's very difficult to understand:

1. **Why was a task added to the task queue?** What sequence of events led to it being scheduled?
2. **What is the causal chain?** When a coroutine awaits, the Python stack trace only shows the event loop, not the async caller chain.
3. **What commands caused what side effects?** Commands can enqueue nodes, resume tasks, etc.

## The Problem We're Debugging

We have a stream producer/consumer hang where:
- Consumer1 completes generation (0,) and exits its function body
- Consumer1 immediately re-enters and starts consuming generation (1,) data
- This causes an infinite loop

We can see WHAT happens, but not WHY Consumer1 gets restarted. What command triggered it? What was the causal chain?

## Your Task

Build a **tracing and explainability system** for the flowno event loop that answers:

1. **Task Queue Tracing**: When a task is added to the task queue, record WHY (with a growing trace of causes)
2. **Async Stack Traces**: Provide cleaner "fake stack traces" that show the async call chain, not just the event loop
3. **Command History**: Track what commands caused what side effects (enqueuing, barriers, etc.)

## Design Considerations

### 1. Task Queue Tracing

The current task queue holds coroutines that get re-entered frequently. You need to track:

- **Initial cause**: Why was this task first created?
- **Resume causes**: Each time a task is resumed, why? (e.g., "barrier released", "queue had data", "node stalled request")
- **Accumulating history**: A trace that grows as the coroutine progresses through await points

**Suggestion**: Similar to `AsyncMapQueue`, but for tasks. Maybe:
```python
task_trace: dict[RawTask, list[str]] = {}
```

When a task yields a command and gets resumed, append the reason to its trace.

### 2. Async Stack Traces

Python's normal stack traces for async code are unhelpful - they don't show async callers. You need to build a system that tracks:

- When task A awaits task B, record this relationship
- When an exception occurs, reconstruct the "async call chain"
- Make it easy to print a trace like:
  ```
  Consumer1 at generation (1,)
    → awaited Stream.__anext__()
    → called _node_stalled(producer)
    → enqueued producer on resolution queue
    → because: ["completed generation (0,)", "barrier released"]
  ```

### 3. Command Side Effect Tracking

Commands like `StalledNodeRequestCommand`, `StartNextGenerationCommand`, etc. have side effects. Track:

- What command was yielded
- What side effects it triggered (nodes enqueued, barriers released, etc.)
- The current state when it happened (generation, queue lengths, etc.)

## Implementation Approach

### Phase 1: Basic Instrumentation

1. **Modify the event loop** (`src/flowno/core/event_loop/event_loop.py`):
   - Add a `TaskTracer` class to track task causes
   - In the main loop (around line 742), when resuming tasks, record the reason
   - When handling commands, log side effects

2. **Key locations**:
   - `_run_event_loop_core()` (line 622+): Main event loop
   - Task queue operations (around line 742): Where tasks get resumed
   - Command handlers: Where side effects happen

3. **Data structure**:
   ```python
   class TaskTracer:
       def __init__(self):
           self.traces: dict[RawTask, list[str]] = {}

       def record_cause(self, task: RawTask, cause: str):
           if task not in self.traces:
               self.traces[task] = []
           self.traces[task].append(cause)

       def get_trace(self, task: RawTask) -> list[str]:
           return self.traces.get(task, [])
   ```

### Phase 2: Integrate with Resolution Queue

1. **Replace `AsyncSetQueue` with `AsyncMapQueue`** for the resolution queue in `src/flowno/core/flow/flow.py`

2. **Modify `_enqueue_output_nodes()`** (flow.py:688-703) to include the reason:
   ```python
   await self.resolution_queue.put((node, f"output of {source_node.name} at generation {source_node.generation}"))
   ```

3. **Track all enqueue points**:
   - `_handle_async_generator_node()` (flow.py:427-540): When barriers release
   - `evaluate_node()` (flow.py:595-623): When nodes complete generations
   - `_node_stalled()` commands: When stream consumers demand data

### Phase 3: Async Stack Trace Reconstruction

1. **Track await relationships**: When task A awaits and yields a command that creates/resumes task B, record the relationship

2. **Build a call graph**: Maintain parent-child relationships between tasks

3. **Pretty printer**: Function to print the async call chain with context

### Phase 4: Debug Output

Add a debug mode that prints:
- When nodes are enqueued (with full cause trace)
- When tasks are resumed (with reason)
- When commands trigger side effects
- Current state (queue lengths, generations, etc.)

## Test Scenario

Use `test_exact_pattern.py` as your test case. When it hangs, the tracing system should output something like:

```
[Consumer1] Enqueued on resolution queue
  Causes: ["completed generation (0,)"]

[Consumer1] Resumed from resolution queue
  Starting generation (1,)

[Consumer1] Called __anext__() on Stream
  Stream detected no data at generation (1,0)

[Consumer1] Yielded StalledNodeRequestCommand(ThreeChunkSource)

[ThreeChunkSource] Enqueued on resolution queue
  Causes: ["stalled request from Consumer1"]

[ThreeChunkSource] Resumed from resolution queue
  Already finished (raised StopAsyncIteration)
  Pushing run-level-0 data

[Consumer1] Enqueued on resolution queue
  Causes: ["completed generation (0,)", "output of ThreeChunkSource at generation (1,0)"]

← LOOP DETECTED: Consumer1 already processing generation (1,)
```

## Deliverables

1. **TaskTracer class** in a new file `src/flowno/core/event_loop/tracing.py`
2. **Integration** with event loop main loop
3. **Modified resolution queue** using `AsyncMapQueue` with cause tracking
4. **Debug mode** that can be enabled via environment variable or flag
5. **Tests** that verify tracing captures the right information
6. **Documentation** on how to use the tracing system to debug issues

## Files to Examine

- `src/flowno/core/event_loop/event_loop.py`: Main event loop (lines 622-800)
- `src/flowno/core/flow/flow.py`: Flow execution, node scheduling (lines 427-703)
- `src/flowno/core/node_base.py`: Stream class, `_node_stalled()` (lines 802-876)
- `src/flowno/core/event_loop/queues.py`: Queue implementations, `AsyncMapQueue`
- `test_exact_pattern.py`: Test case that reproduces the hang

## Success Criteria

When you run `test_exact_pattern.py` with tracing enabled, you should be able to see:
1. Why Consumer1 gets enqueued after completing generation (0,)
2. What command causes Consumer1 to start generation (1,)
3. The full causal chain leading to the infinite loop
4. Clear async stack traces if an exception occurs

## Notes

- Performance: It's okay if tracing adds overhead. We can disable it in production.
- The user has been debugging this for days - clarity is more important than elegance.
- The `AsyncMapQueue` is already implemented and tested, ready to use.
- Focus on making the output **human-readable** and **actionable** for debugging.

## Questions to Answer

Your tracing system should help answer:
1. Does Consumer1 get a `StartNextGenerationCommand`? If so, where from?
2. Is the `while True` loop in `evaluate_node` the issue?
3. How does the framework detect "all stream consumers are done"?
4. Why doesn't the "both consumers don't check" case hang, but the "mixed" case does?

Good luck! This will be a valuable debugging tool for the entire flowno codebase.
