# Stream Cancellation Deadlock Investigation Plan

## Executive Summary

**Bug**: After a node calls `await stream.cancel()` and returns a new value, the upstream stream-producing node is never scheduled for the next iteration, causing a deadlock.

**Minimal Reproduction**: `examples/cancel_deadlock_example.py` demonstrates a 2-node circular graph where:
- Node A (StreamIn_Out): consumes optional stream, returns int
- Node B (MonoIn_Stream): takes int, yields stream
- After A cancels stream mid-iteration and returns value 2, B never executes with input 2

**Status**: Investigation phase - root cause unknown

**Created**: 2025-12-03

---

## Problem Space Analysis

### Observed Behavior

1. **Iteration 1** (Success):
   - StreamIn_Out returns 1 (no stream input on first iteration)
   - MonoIn_Stream receives 1, begins yielding tokens
   - StreamIn_Out consumes 5 tokens from the stream

2. **Cancellation**:
   - Cancel flag is set
   - StreamIn_Out calls `await input_stream.cancel()`
   - `cancel()` returns successfully
   - StreamIn_Out exits stream loop and returns 2

3. **Deadlock** (Iteration 2 never starts):
   - MonoIn_Stream is never called with input value 2
   - System hangs indefinitely
   - No exceptions or errors logged

### Critical Code Paths

#### 1. Stream Cancellation Handler
**Location**: `src/flowno/core/flow/flow.py:1250-1272`

```python
elif isinstance(command, StreamCancelCommand):
    producer_node = command.producer_node
    stream = command.stream
    current_task = current_task_packet[0]

    self.flow._cancelled_streams[producer_node].add(stream)

    # Lines 1258-1268 are COMMENTED OUT - SUSPICIOUS!
    # Commented code attempted to resume the producer node immediately

    # Current implementation only resumes consumer task
    self.tasks.insert(0, (current_task, None, None))
```

**Key Observation**: Lines 1258-1268 contain commented-out code that would have resumed the producer node. This suggests a known issue or previous attempt to fix this problem.

#### 2. Async Generator Lifecycle
**Location**: `src/flowno/core/flow/flow.py:441-583`

Handles streaming nodes:
- Checks `_cancelled_streams` at start of each iteration (line 470)
- Throws `StreamCancelled` to generator if cancelled (lines 491-492)
- On completion (`StopAsyncIteration`), pushes final data
- Calls `_enqueue_output_nodes()` in `finally` block (line 637)

#### 3. Output Node Enqueueing Logic
**Location**: `src/flowno/core/flow/flow.py:702-741`

Special logic for streaming consumers (lines 725-736):
```python
# For streaming consumers: skip if they're in Ready status and at same/higher generation
if is_streaming_consumer and output_node in self.node_tasks:
    status = self.node_tasks[output_node].status
    if isinstance(status, NodeTaskStatus.Ready):
        if (output_node.generation >= out_node.generation):
            logger.debug(f"Skipping enqueue of streaming consumer...")
            continue
```

**CRITICAL HYPOTHESIS**: This logic might be incorrectly skipping the producer node after cancellation.

---

## Investigation Phases

### Phase 1: State Inspection - Where Does the System Get Stuck?

**Objective**: Identify exactly which node is stuck and what state it's in

**Techniques**:

1. **Add comprehensive logging at critical checkpoints**:
   - [ ] Node generation counters when entering/exiting `evaluate_node()`
   - [ ] Node task status transitions (Ready → Running → Stalled)
   - [ ] Resolution queue operations (put/get/close)
   - [ ] `_enqueue_output_nodes()` decisions (which nodes enqueued, which skipped)

2. **Snapshot key data structures when deadlock is detected**:
   - [ ] `flow.node_tasks` - status of each node task
   - [ ] `flow._cancelled_streams` - any lingering cancelled streams?
   - [ ] `flow.resolution_queue` - is it empty? closed?
   - [ ] Each node's `generation` counter
   - [ ] Each node's barriers (`_barrier0`, `_barrier1`) - are they waiting?

3. **Add instrumentation to the test**:
   - [ ] Poll and log node states every 500ms during the wait period
   - [ ] Check if producer/consumer tasks are in event loop's task queue
   - [ ] Verify if `unvisited` list is empty (no new nodes to schedule)

**Expected Findings**:
- Is MonoIn_Stream's task status "Stalled" waiting for data, or "Ready" but not scheduled?
- Is StreamIn_Out stuck waiting at a barrier?
- Is the resolution queue empty or blocked?

---

### Phase 2: Scheduling Investigation - Why Isn't the Producer Scheduled?

**Objective**: Trace why MonoIn_Stream doesn't get added to the resolution queue for iteration 2

**Key Hypothesis**: The issue is in `_enqueue_output_nodes()` lines 725-736 - the streaming consumer skip logic

**Techniques**:

1. **Instrument `_enqueue_output_nodes()`**:
   - [ ] Add detailed logging for each output node check
   - [ ] Log: `is_streaming_consumer` flag
   - [ ] Log: node task status
   - [ ] Log: generation values (output_node vs source_node)
   - [ ] Log: skip vs enqueue decision

2. **Test specific scenarios**:
   - [ ] Remove streaming consumer skip logic entirely - does deadlock disappear?
   - [ ] Force-enqueue producer after cancellation - does it work?
   - [ ] Check generation comparison (line 734) - is it failing incorrectly?

3. **Trace generation advancement**:
   - [ ] Log when each node increments its generation
   - [ ] Check generation values immediately after cancellation
   - [ ] Look for race conditions where generations are out of sync

**Questions to Answer**:
- Does StreamIn_Out call `_enqueue_output_nodes()` when it completes iteration 1?
- Does MonoIn_Stream get filtered out by the streaming consumer logic?
- Are the generation comparisons working correctly post-cancellation?

---

### Phase 3: Cancellation Flow Analysis - What Happens During Cancel?

**Objective**: Understand the complete state transition during `stream.cancel()`

**Techniques**:

1. **Trace the cancellation sequence step-by-step**:
   - [ ] Consumer calls `await stream.cancel()` at `node_base.py:793`
   - [ ] Yields `StreamCancelCommand` to event loop
   - [ ] Handler adds stream to `_cancelled_streams` (line 1256)
   - [ ] Handler resumes consumer task (line 1272)
   - [ ] **Critical Question**: What happens to the producer task?

2. **Test the commented-out code** (lines 1258-1268):
   - [ ] Uncomment the producer resume logic
   - [ ] Run test - does it fix the deadlock?
   - [ ] Check git history - why was it commented out?
   - [ ] Test for side effects or regressions

3. **Examine producer's cancellation handling**:
   - [ ] When producer's `_handle_async_generator_node()` catches `StreamCancelled`
   - [ ] Does it exit cleanly via `StopAsyncIteration`?
   - [ ] Does the `finally` block execute and call `_enqueue_output_nodes()`?
   - [ ] Is there a path where producer never reaches `_enqueue_output_nodes()`?

**Expected Insights**:
- The commented-out code likely attempted to fix this exact issue
- There may be a missed state transition where the producer needs explicit wakeup
- The cancellation might leave the producer in an unexpected state

---

### Phase 4: Barrier & Synchronization Analysis - Are We Deadlocked on Barriers?

**Objective**: Verify that barrier coordination isn't causing the hang

**Techniques**:

1. **Instrument barrier operations**:
   - [ ] Log all `barrier.wait()` calls with node name and run level
   - [ ] Log all `barrier.countdown()` calls
   - [ ] Track barrier counts: expected vs actual
   - [ ] Verify all streaming data was consumed before cancellation

2. **Check for missed countdown**:
   - [ ] Review `_stream_get()` in `node_base.py:849-941`
   - [ ] Does cancellation path (line 928) properly countdown `barrier1`?
   - [ ] Trace barrier1 lifecycle during cancellation

3. **Verify generation wait logic**:
   - [ ] Analyze `_wait_for_start_next_generation()` - what wakes it up?
   - [ ] Is the producer stuck waiting for `WaitForStartNextGenerationCommand`?
   - [ ] Who is responsible for sending that command?

**Questions**:
- Are both nodes properly releasing barriers?
- Is there a barrier deadlock independent of the scheduling issue?

---

### Phase 5: Resolution Queue Mechanics - Is the Queue Functioning?

**Objective**: Verify the resolution queue and node resolution loop are working correctly

**Techniques**:

1. **Trace `_node_resolve_loop()`** (`flow.py:814-871`):
   - [ ] Is the loop still running or has it exited?
   - [ ] Check if `unvisited` list is empty
   - [ ] Verify `resolution_queue.closed` status
   - [ ] Monitor queue operations: what goes in, what comes out

2. **Test `_find_node_solution()`**:
   - [ ] When producer is requested, what is the "solution"?
   - [ ] Does Tarjan's algorithm for cycles work correctly post-cancellation?
   - [ ] Are there circular dependencies being broken incorrectly?

3. **Examine queue closing conditions**:
   - [ ] When does `resolution_queue` get closed?
   - [ ] Could premature closure prevent producer from being scheduled?

**Specific Probes**:
- Add a periodic task that dumps resolution queue state
- Force-enqueue the producer manually after 2 seconds
- Check if manually enqueueing fixes the deadlock

---

### Phase 6: Event Loop Task Management - Is the Producer Task Lost?

**Objective**: Ensure the producer task still exists and can be scheduled

**Techniques**:

1. **Inspect task states in event loop**:
   - [ ] Check `event_loop.tasks` deque
   - [ ] Verify producer task is in `flow.node_tasks`
   - [ ] Confirm task hasn't been cancelled or lost

2. **Test task resumption**:
   - [ ] Try manually calling `_resume_node(producer)` after cancellation
   - [ ] Check if `ResumeNodeCommand` gets handled correctly
   - [ ] Verify the producer task responds to resume attempts

3. **Check for task cancellation**:
   - [ ] Was producer task accidentally cancelled?
   - [ ] Are there any exceptions in the producer that killed it?

---

## Prioritized Investigation Plan

### Step 1: Instrument `_enqueue_output_nodes()` ⭐ HIGHEST PRIORITY

**Why**: Most likely culprit - commented code strongly suggests a known issue here

**How**:
- Add detailed logging to see if producer gets skipped
- Log all decision points in the streaming consumer logic
- Capture generation values at time of decision

**Test**: Run `examples/cancel_deadlock_example.py` with instrumentation

**Expected Outcome**: Identify if/why producer is being skipped

---

### Step 2: Test the Commented-Out Code

**Why**: Quick validation if producer resume fixes the issue

**How**:
- Uncomment lines 1258-1268 in `flow.py`
- Run test and observe behavior
- Check for any side effects or test failures

**Outcomes**:
- If it works → confirms the root cause is lack of producer scheduling
- If it breaks → learn what constraints exist that prevent this approach

---

### Step 3: Add Comprehensive State Snapshots

**Why**: Get full picture of system state at deadlock

**How**:
- Modify test to dump all node states when deadlock detected
- Include task states, queues, generations, barriers
- Create a detailed system state report

**Expected Outcome**: Definitive data on what's stuck where

---

### Step 4: Trace Generation Counters

**Why**: Generation comparison logic is complex and could be failing

**How**:
- Log generation values at every transition
- Track generation advancement through cancellation
- Verify generation comparisons in enqueueing logic

**Expected Outcome**: Identify if generations are out of sync

---

### Step 5: Verify Barrier Coordination

**Why**: Rule out barrier deadlock as separate issue

**How**:
- Log all barrier operations and verify counts
- Trace barrier lifecycle during cancellation
- Ensure all consumers properly countdown

**Expected Outcome**: Confirm barriers aren't the root cause

---

## Code Locations to Probe

| Location | What to Check | Why | Priority |
|----------|---------------|-----|----------|
| `flow.py:1258-1268` | Why was producer resume commented out? | Direct evidence of known issue | ⭐⭐⭐ |
| `flow.py:725-736` | Does streaming consumer skip logic fire incorrectly? | Likely prevents producer enqueue | ⭐⭐⭐ |
| `flow.py:637` | Is this reached after cancellation? | Verify finally block executes | ⭐⭐ |
| `flow.py:522` | Is `_enqueue_output_nodes()` called during stream iteration? | May not enqueue while streaming | ⭐⭐ |
| `node_base.py:928` | Does cancel path handle barriers correctly? | Ensure no barrier leak | ⭐ |
| `flow.py:470-492` | Does producer receive cancelled notification? | Verify cancellation propagates | ⭐ |

---

## Root Cause Hypotheses (Ranked by Likelihood)

### 1. Most Likely: Enqueueing Logic Bug
**Hypothesis**: `_enqueue_output_nodes()` incorrectly skips the producer due to streaming consumer logic (lines 725-736) after cancellation.

**Evidence**:
- Commented-out code suggests known scheduling issue
- Skip logic checks generation and status - could fail post-cancellation
- This is the only place where downstream nodes are scheduled

**Test**: Instrument or bypass this logic

---

### 2. Very Likely: Missing Producer Resume
**Hypothesis**: Producer needs explicit resume after cancellation, which the commented code attempted to provide.

**Evidence**:
- Lines 1258-1268 explicitly tried to resume producer
- Current code only resumes consumer
- Producer may be waiting indefinitely for next generation signal

**Test**: Uncomment the producer resume code

---

### 3. Possible: Generation Counter Desynchronization
**Hypothesis**: Generation counters are out of sync after cancellation, causing enqueueing logic to make wrong decisions.

**Evidence**:
- Complex generation tracking across iterations
- Cancellation interrupts normal flow
- Generation comparisons in skip logic (line 734)

**Test**: Log all generation values through cancellation sequence

---

### 4. Less Likely: Barrier Coordination Issue
**Hypothesis**: Barrier coordination prevents iteration advancement.

**Evidence**:
- Barriers used for synchronization between producer/consumer
- Cancellation path may not properly release barriers

**Test**: Instrument all barrier operations

---

### 5. Unlikely: Resolution Queue or Task Loss
**Hypothesis**: Resolution queue is closed prematurely or task is lost.

**Evidence**:
- Less likely given the persistent nature of node tasks
- No evidence of queue closure issues

**Test**: Monitor queue state and task existence

---

## Architecture Context

### Stream Implementation
**File**: `src/flowno/core/node_base.py:748-810`

Key components:
- `Stream` class implements `AsyncIterator[_InputType]`
- Tracks `_last_consumed_generation`, `_cancelled` flag
- `cancel()` method yields `StreamCancelCommand`
- `__anext__()` delegates to `_stream_get()` for iteration logic

### Flow Execution
**File**: `src/flowno/core/flow/flow.py`

Key components:
- `FlowEventLoop` - custom event loop with Flow-specific commands
- `evaluate_node()` - persistent task loop for each node (lines 586-637)
- `_handle_async_generator_node()` - streaming iteration loop (lines 441-583)
- `_node_resolve_loop()` - dependency resolution using Tarjan's algorithm (lines 814-871)
- `_enqueue_output_nodes()` - schedules downstream nodes (lines 702-741)

### Synchronization
**File**: `src/flowno/core/event_loop/synchronization.py`

Key components:
- `CountdownLatch` - barriers for run level 0 and 1 data
- `node._barrier0` - waits for final data consumption
- `node._barrier1` - waits for stream data consumption

---

## Next Steps

1. **Immediate**: Implement Phase 1 logging to capture system state at deadlock
2. **Quick Win**: Test commented-out code (Step 2) to validate hypothesis
3. **Deep Dive**: Instrument `_enqueue_output_nodes()` (Step 1) for detailed trace
4. **Validation**: Add comprehensive test suite for cancellation scenarios

---

## Success Criteria

- [ ] Root cause identified with supporting evidence
- [ ] Fix implemented that resolves deadlock
- [ ] All existing tests continue to pass
- [ ] New test added to prevent regression
- [ ] No new deadlocks or race conditions introduced
- [ ] Documentation updated to explain cancellation behavior

---

## References

- **Bug Reproduction**: `examples/cancel_deadlock_example.py`
- **Core Flow Logic**: `src/flowno/core/flow/flow.py`
- **Stream Implementation**: `src/flowno/core/node_base.py`
- **Event Loop**: `src/flowno/core/event_loop/event_loop.py`
- **Synchronization**: `src/flowno/core/event_loop/synchronization.py`
