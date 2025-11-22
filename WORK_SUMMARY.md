# Concurrency Debugging Work Summary

## What I Did

I spent several hours investigating the concurrency timeout issue in `test_stream_multiple_chunks_delayed_consumption`. Here's a summary of my findings and progress.

## The Problem

The test creates a streaming source that yields 3 chunks ("alpha", "beta", "gamma"), with two consumers:
- **Consumer1**: Uses explicit `__anext__()` calls with variable delays
- **Consumer2**: Uses `async for` with consistent 30ms delays AFTER each read

The test times out after 5 seconds due to an infinite loop where the source keeps restarting.

## Root Cause Identified

**Classic race condition between barrier release and generator completion:**

1. Source yields "gamma" at generation (0, 2) and waits at barrier (count=2)
2. Both consumers read "gamma", counting down the barrier to 0
3. Barrier is released - source CAN continue now
4. Consumer2 sleeps for 30ms after reading
5. Consumer2 wakes up and tries to get the next chunk
6. At this point, Source is still at generation (0, 2) - it hasn't had a chance to run yet!
7. Consumer2 sees `current_generation (0,2) == last_consumed (0,2)` and requests new data
8. This queues Source for resumption
9. Source finally runs, generator raises StopAsyncIteration
10. Source restarts to generation (1, 0)
11. Both consumers start consuming from (1, 0) again
12. **Infinite loop**

### The Fundamental Issue

The barrier countdown happens AFTER consumers read data (in `_stream_get`, node_base.py:918-922). This ensures the source doesn't produce new data until all consumers have read the current data. However, it doesn't prevent consumers from requesting new data BEFORE the source has had a chance to finish its generator.

There's a window of time between:
- Barrier reaching 0 (all consumers have read)
- Source generator being resumed and raising StopAsyncIteration

During this window, sleeping consumers can wake up and request more data, causing the infinite restart loop.

## What I Tried

### Attempt 1: Move Parent Generation Check Earlier
**File**: `src/flowno/core/node_base.py`

Moved the parent generation change check before the data availability check in `_stream_get`. This helps Consumer2 eventually detect completion, but only AFTER the source has already restarted once.

**Result**: Partial improvement - Consumer2 stops after first restart, but restart still happens.

### Attempt 2: Add Generator Finished Flag
**Files**:
- `src/flowno/core/flow/flow.py` - Added `_generator_finished` set
- `src/flowno/core/node_base.py` - Check flag before requesting data

Added a flag that gets set when a generator raises StopAsyncIteration and cleared when it restarts.

**Result**: FAILED - The flag is set too late! By the time StopAsyncIteration is raised and the flag is set, Consumer2 has already requested new data.

**Timeline showing why it failed**:
```
1. Source yields (0,2), waits at barrier
2. Consumers read, barrier -> 0
3. Barrier releases
4. Consumer2 wakes from sleep
5. Consumer2 checks _generator_finished (FALSE - not set yet!)
6. Consumer2 requests new data
7. Source resumes, StopAsyncIteration raised
8. Flag set (TOO LATE)
```

## Key Insight

**We cannot know if a generator will raise StopAsyncIteration without actually calling `__anext__()` on it.**

This means any flag-based solution that tries to check "is the generator finished?" will fail because:
- The flag can only be set AFTER we call `__anext__()` and it raises StopAsyncIteration
- But consumers check the flag BEFORE calling `__anext__()`
- There's always a race between barrier release and flag setting

## Recommended Solutions (Not Yet Implemented)

### Option A: Two-Phase Barrier System (RECOMMENDED)
Add a second barrier phase:
1. **barrier1**: All consumers have read current data (existing)
2. **Peek phase**: Source checks if generator has more data
3. **Flag set**: If no more data, set `_generator_finished`
4. **barrier2**: All consumers acknowledge the flag
5. **Continue/Finish**: Based on flag, either continue or stop

### Option B: Last Chunk Metadata
Modify the protocol so producers can signal "this is my last chunk" when yielding:
- Change `yield "data"` to `yield ("data", is_last=True)`
- Consumers check the metadata and don't request more if `is_last=True`
- Requires protocol change

### Option C: Defer Restart Until All Consumers Complete
Track which consumers are still actively consuming a stream:
- Don't restart generator until all consumers have raised StopAsyncIteration
- Requires tracking consumer state more carefully

## Files Modified

1. **src/flowno/core/node_base.py**
   - Moved parent generation check earlier in `_stream_get`
   - Added generator finished flag check
   - Both attempts are in the current code but don't fully solve the problem

2. **src/flowno/core/flow/flow.py**
   - Added `_generator_finished` set to track completed generators
   - Set flag in StopAsyncIteration handler
   - Clear flag when generator restarts

3. **DEBUGGING_NOTES.md** (NEW)
   - Detailed analysis of the race condition
   - Trace comparisons between passing and failing tests
   - Timeline of events showing where the bug occurs

4. **test_output.log** (NEW)
   - Full test run output showing 1 failure

## Commits Made

1. `58ec015` - WIP: Attempt to fix with early parent generation check
2. `e62091e` - docs: Add detailed debugging notes
3. `84fc6ab` - WIP: Add generator_finished flag (incomplete)
4. `dd0a101` - docs: Update DEBUGGING_NOTES with analysis

## Test Results

- **All non-network tests**: 273 passed, 1 failed (test_stream_multiple_chunks_delayed_consumption)
- **Failing test status**: Still times out after 5 seconds
- **No regressions**: All previously passing tests still pass

## Next Steps for Human Developer

1. Review `DEBUGGING_NOTES.md` for complete analysis
2. Choose a solution approach (I recommend Option A: Two-Phase Barrier)
3. Implement the chosen solution
4. Test with: `pytest tests/test_streaming.py::test_stream_multiple_chunks_delayed_consumption -v`
5. Run full test suite: `pytest tests/ -m "not network" -v`
6. The AsyncMapQueue that was added in commit b886dbe might be part of an intended solution - investigate its purpose

## Logging Analysis

I used DEBUG-level logging to trace execution and found:
- Barriers work correctly for their intended purpose (preventing premature data generation)
- Generation tracking works correctly
- Parent generation change detection works correctly
- The issue is purely a timing/scheduling problem, not a logic error

The fix requires a synchronization mechanism that doesn't exist yet - either:
- A way to peek at generator state without consuming it
- An additional synchronization barrier
- A protocol change to signal completion earlier

## Time Spent

Approximately 3 hours of autonomous debugging:
- 1 hour: Understanding the codebase and tracing execution
- 1 hour: Implementing and testing first attempted fix
- 1 hour: Implementing and testing second attempted fix
- Documentation throughout

The problem is well-understood now, but requires architectural changes to fix properly.
