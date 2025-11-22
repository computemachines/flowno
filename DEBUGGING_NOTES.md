# Stream Concurrency Issue - Debugging Notes

## Problem Summary
Test `test_stream_multiple_chunks_delayed_consumption` times out after 5 seconds, indicating a deadlock or infinite loop in stream consumption.

## Root Cause Analysis

### The Failing Pattern
1. Source node (`ThreeChunkSource`) yields 3 chunks: "alpha", "beta", "gamma"
2. Consumer1 consumes all 3 chunks using explicit `__anext__()` calls and completes
3. Consumer2 consumes chunks using `async for` with 30ms delays AFTER each read
4. **Critical race condition**: After Consumer2 reads 'gamma':
   - Consumer2 sleeps for 30ms
   - Consumer2's sleep finishes
   - Consumer2 tries to get next chunk (expects StopAsyncIteration)
   - But ThreeChunkSource is still at generation (0, 2) - hasn't finished yet!
   - Consumer2 requests new data
   - ThreeChunkSource finishes and RESTARTs to generation (1, 0)
   - Both consumers start consuming from generation (1, 0) again
   - **Infinite loop**

### The Barrier Timing Issue
The barrier countdown happens AFTER a consumer reads data:
```python
# In _stream_get (node_base.py:918-922)
data = stream.output.node.get_data(run_level=stream.run_level)
yield from stream.output.node._barrier1.count_down()  # AFTER reading
return data
```

This means:
1. Producer yields data and waits at barrier
2. All consumers READ the data (triggering barrier countdown)
3. Barrier reaches 0 and releases producer
4. BUT some consumers may still be sleeping after their sleep() calls
5. Producer continues and finishes its generator
6. Sleeping consumers wake up and try to read more
7. They see current_generation == last_consumed_generation
8. They request new data, restarting the producer

### Why Parent Generation Check Doesn't Work (Current Attempt)
I moved the parent generation check before the data availability check:
```python
# Check if parent generation changed
current_parent_gen = parent_generation(stream.output.node.generation)
if (state.last_consumed_generation is not None
    and current_parent_gen != state.last_consumed_parent_generation):
    raise StopAsyncIteration

# Check if data is available
while cmp_generation(get_clipped_stitched_gen(), state.last_consumed_generation) <= 0:
    yield from _node_stalled(stream.input, stream.output.node)  # Request new data
```

This fails because:
- When Consumer2 wakes up after sleeping, Producer is STILL at generation (0, 2)
- parent_generation((0, 2)) = (0,)
- last_consumed_parent_generation = (0,)
- Check passes, no exception raised
- Data availability check: (0, 2) <= (0, 2), so request new data
- Producer restarts

## Possible Solutions

### Option 1: Add "Generator Finished" Flag
Track when a generator has yielded its last value:
- Set flag when `StopAsyncIteration` is caught in `_handle_async_generator_node`
- Check flag before requesting new data
- Clear flag when generator restarts

### Option 2: Change Barrier Mechanism
Move the barrier countdown to BEFORE the sleep/processing:
- Consumers count down barrier immediately after reading
- But don't sleep or process until all consumers have read
- This ensures producer can't continue until all consumers are ready

### Option 3: AsyncMapQueue Deduplication
Use AsyncMapQueue to deduplicate node restart requests:
- Multiple consumers requesting same node only queues it once
- But this doesn't prevent the first request from restarting the node

### Option 4: Two-Phase Barrier
- barrier1: All consumers have read the data (current)
- barrier2: All consumers are ready for next iteration (new)
- Producer waits on both barriers before continuing

## Test Trace Comparison

### Passing Test (test_stream_two_consumers_both_delayed)
- SingleChunkSource yields 1 chunk
- Both consumers read and then try to get more
- Source finishes at (0,)
- Parent generation changes from (0,) to ()
- Both consumers detect change and stop
- ✓ No restart

### Failing Test (test_stream_multiple_chunks_delayed_consumption)
- ThreeChunkSource yields 3 chunks
- Consumer2 sleeps AFTER each read
- After 3rd chunk, Consumer2 requests more while source is still at (0, 2)
- Source restarts before Consumer2 can detect completion
- ✗ Infinite loop

## Attempted Fix: Generator Finished Flag (INCOMPLETE)

Attempted to add `_generator_finished` set to track completed generators:
- Added flag to Flow.__init__
- Set flag when StopAsyncIteration is caught
- Clear flag when generator restarts
- Check flag in _stream_get before requesting data

### Why It Didn't Work
The flag is set TOO LATE in the execution sequence:

```
Timeline:
1. Producer yields last chunk at (0,2) and waits at barrier (count=2)
2. Consumer1 reads chunk (barrier -> 1)
3. Consumer2 reads chunk (barrier -> 0) and sleeps for 30ms
4. Barrier reaches 0 and releases producer
5. Consumer2 wakes from sleep
6. Consumer2 checks _generator_finished (FALSE - not set yet!)
7. Consumer2 requests new data (current_gen (0,2) == last_consumed (0,2))
8. Producer is queued for resumption
9. Producer resumes, generator __anext__ raises StopAsyncIteration
10. Flag is set (TOO LATE - restart already queued)
```

The fundamental issue: We can't know if a generator has more data without actually calling `__anext__()` on it, which happens AFTER the barrier is released.

## Next Steps
1. **Option A: Two-Phase Barrier System**
   - barrier1: All consumers have read current data (existing)
   - barrier2: All consumers are ready for next iteration (new)
   - Set flag between barrier1 release and barrier2 setup
   - Consumers check flag before barrier2 countdown

2. **Option B: "Last Chunk" Metadata**
   - Modify yield behavior to include "is_last" flag
   - Producers signal when yielding their final chunk
   - Consumers check this flag to know not to request more

3. **Option C: Peek-Ahead Mechanism**
   - After barrier release, peek if generator has more data
   - Set flag based on peek result
   - Block consumers until peek is complete

4. **Option D: AsyncMapQueue with Completion Tracking**
   - Use AsyncMapQueue to deduplicate restart requests
   - Add completion tracking to prevent any restart after StopAsyncIteration
   - May still need flag to prevent initial restart request

**Recommendation**: Try Option A (Two-Phase Barrier) as it provides a clean synchronization point where we can definitively set the completion flag before any consumer can request new data.
