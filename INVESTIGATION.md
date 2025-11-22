# Stream Consumer State Keying Investigation

## Original Issue
- Test `test_stream_multiple_chunks_delayed_consumption` times out after 5s
- Root cause: Stream consumer state was keyed by Stream object identity
- Stream objects are recreated on each `gather_inputs()` call
- New Stream → lookup fails → fresh state → consumer re-reads same data infinitely

## First Fix Attempt: Stable Port-Based Keying
**Change**: Key by `(consumer_node, consumer_port, producer_node, producer_port)` instead of Stream object

**Result**: Fixed timeout but introduced 13 regressions in cyclic flow tests

**Problem**: State persists across consumer re-executions in cyclic flows
- Consumer execution 1: Consumes stream, state updated
- Consumer execution 2: Finds same state from execution 1, detects parent generation change, raises StopAsyncIteration prematurely

## Second Fix Attempt: Add Producer Parent Generation to Key  
**Change**: Key by `(..., parent_generation(producer.generation))`

**Result**: Still fails with deadlock

**Problem**: Producer advances to new parent generation while consumers are mid-execution
- Creates different state keys for what should be the same consumption session
- Consumers get StopAsyncIteration when they shouldn't

## Third Fix Attempt: Add Consumer Generation to Key
**Change**: Key by `(..., consumer.generation)`

**Result**: Test still times out (9 failures total vs original 1)

**Problem**: Consumer generation changes DURING execution!
- Consumer starts at `generation=None`
- Consumes first chunk, state updated with key `(..., None)`
- Consumer calls `push_data()` mid-execution, advances to `generation=(0,)`
- Next stream read uses key `(..., (0,))` → different state → infinite loop

### Evidence from Logs
```
2025-11-22 17:36:50,759 - Consumer1#0 advanced to generation (0,) with data=(None,)
```
This happens BEFORE the consumer finishes consuming all stream chunks.

## Root Cause Analysis

The fundamental issue is that:
1. Stream objects are transient (recreated per `gather_inputs()`)
2. Stream consumption state needs to persist within a consumer execution
3. Stream consumption state needs to reset between consumer executions  
4. Consumer generation changes DURING execution, not just between executions
5. No stable identifier exists that:
   - Persists within a single consumer execution
   - Changes between consumer executions
   - Is available at the time of stream consumption

## Architectural Challenge

The current design has no way to distinguish "same execution, different Stream object" from "different execution, different Stream object" because:
- Stream objects themselves are transient
- Consumer generation is None initially and changes mid-execution
- Producer generation tracks producer state, not consumer execution boundaries

## Potential Solutions (Not Implemented)

1. **Add execution ID to consumer nodes**: Track a counter that increments only between executions, not during
   - Requires modifying node architecture

2. **Make Stream objects persistent**: Don't recreate Stream on each `gather_inputs()`
   - Requires changing how `gather_inputs()` works

3. **Track Stream lineage**: When creating new Stream, link to previous Stream for same port connection
   - Complex state transfer logic needed

4. **Rethink state storage**: Store state differently, not in a global dict
   - Major architectural change

## Conclusion

This is not a simple keying fix but a fundamental architectural issue with how stream consumption state is tracked across transient Stream objects and evolving node generations.
