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

## Next Steps
1. Implement Option 1 (Generator Finished Flag) as most straightforward
2. Test with all streaming tests
3. Consider Option 4 (Two-Phase Barrier) if Option 1 doesn't work
4. Document the fix and why it works
