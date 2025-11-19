# Node Lifecycle Analysis

## Node States (NodeTaskStatus)
- **Ready**: Node is waiting, can be resumed
- **Running**: Node is actively executing
- **Stalled**: Node is blocked waiting for input
- **Error**: Node encountered an exception

## Commands and Their Contracts

### WaitForStartNextGenerationCommand(node, run_level)
**Yields from**: Line 592 in evaluate_node's while True loop
**Handled by**: Lines 1080-1086
**Effect**:
  - Sets node status to Ready
  - Suspends the generator
  - If no running nodes and empty queue: close queue (flow ends)

**Question**: What should wake this up? When SHOULD a node start its next generation?

### ResumeNodeCommand(node)
**Yields from**: Line 830 after solver determines node needs to run
**Handled by**: Lines 1100-1114
**Effect**:
  - If node not in running_nodes: mark Running, schedule task
  - If node already running: skip (idempotent)
  - Calls .send() on the generator → resumes from yield point

**Question**: Who decides to resume? What makes it valid to resume?

## The evaluate_node Loop Structure

```python
while True:  # Line 591
    await _wait_for_start_next_generation(node, 0)  # Line 592 - SUSPEND HERE
    # When resumed, we're here:
    gather_inputs()   # Fresh Stream objects
    node.call()       # Fresh coroutine/generator

    if coroutine:
        await _handle_coroutine_node()
    else:
        await _handle_async_generator_node()  # Processes ALL yields

    finally:
        await _enqueue_output_nodes(node)  # Line 619 - ALWAYS RUNS
```

## Critical Observations

### For Mononodes (coroutine consumers):
1. First iteration: Line 592 yields, suspends
2. Solver resumes it: runs to completion
3. Finally block: enqueues outputs
4. **Loops back to 591**: yields again at 592
5. **Question**: Should mononodes EVER iterate the while loop more than once?

### For Streaming Nodes (async generator producers):
1. First iteration: Line 592 yields, suspends
2. Solver resumes: enters _handle_async_generator_node
3. Inner loop processes yields until StopAsyncIteration
4. Finally block: enqueues outputs
5. **Loops back to 591**: yields again at 592
6. **Question**: Generator already exhausted - what should happen?

## Key Questions for Intuition

1. **Generation semantics**: What IS a "generation"?
   - Run level 0 generation: How many times node has produced final output?
   - Run level 1 generation: How many times node has produced streaming chunk?

2. **Enqueue contract**: What does `_enqueue_output_nodes()` mean?
   - "My outputs might need this new data I just produced"?
   - "Wake up anyone waiting on me"?
   - Should it ALWAYS run, or only when there's new data?

3. **While loop invariant**: What should cause another iteration?
   - In cyclic graphs: clearly needs multiple iterations
   - In acyclic graphs: ???
   - Is the loop meant to run until the flow terminates?
   - Or until the node has "nothing more to do"?

4. **The suspension contract**:
   - `_wait_for_start_next_generation()` suspends
   - Who should resume it and when?
   - What makes a "next generation" valid vs invalid?

## Trace Pattern That Feels Wrong

```
Source: Done yielding (generator exhausted)
Source: enqueues [Consumer1, Consumer2]
Source: Status → Ready (suspended)
Solver: processes Consumer1 from queue
Solver: "Consumer1 has stale inputs from Source"
Solver: ResumeNodeCommand(Source)
Source: Status → Running
Source: while loop iterates
Source: gather_inputs() - FRESH inputs
Source: node.call() - FRESH generator
Source: Yielding alpha (SECOND TIME!)
```

## What Feels Off?

The generator **finished** (StopAsyncIteration). The node produced its run level 0 data.
Then it gets resumed and creates a **brand new generator** that starts over.

Is this ever valid behavior? Or is this always wrong?

## Potential Invariant Violations

**Hypothesis 1**: Once a generator raises StopAsyncIteration, that node's evaluate_node
should NEVER loop back. The node is "done" for this flow execution.

**Hypothesis 2**: `_enqueue_output_nodes()` should NOT run when exiting via
StopAsyncIteration, because the outputs were already enqueued during the yield loop.

**Hypothesis 3**: The staleness check (`clipped_gen <= self.generation`) is wrong.
It should be strictly less-than, not less-than-or-equal.

**Hypothesis 4**: Nodes shouldn't wait for "next generation" at all if they're
mononodes or exhausted generators.

---

What does your intuition say? Which hypothesis resonates? Or is it something else entirely?
