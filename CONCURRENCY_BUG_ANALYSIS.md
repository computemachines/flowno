# Concurrency Bug Analysis and Partial Fix

## Problem Summary
The test `test_stream_multiple_chunks_delayed_consumption` fails due to a deadlock/hang when multiple consumers with different delays consume from the same streaming source.

## Root Causes Identified

### 1. Parent Generation Check Ordering (FIXED)
**Issue**: In `_stream_get()` (node_base.py:882-917), the parent generation check happened AFTER the while loop that checks for data readiness. This caused consumers to stall waiting for more data even when the stream had already completed.

**Fix Applied**: Moved the parent generation check INSIDE the while loop, before yielding `StalledNodeRequestCommand`. This ensures `StopAsyncIteration` is raised immediately when a stream completes, rather than attempting to stall.

**Location**: `src/flowno/core/node_base.py` lines 884-896

**Result**: Consumers now properly detect stream completion. All 3 chunks (alpha, beta, gamma) are successfully consumed by both consumers.

### 2. Source Restart Issue (PARTIALLY UNDERSTOOD, NOT YET FIXED)
**Issue**: After both consumers complete successfully, the streaming source restarts with a new parent generation (0,) -> (1, 0), yielding 'alpha' again. This causes `run_until_complete()` to hang indefinitely.

**Observations**:
- Both consumers successfully consume all 3 chunks and complete (advance to generation (0,))
- Source completes and advances to generation (0,) with final value 'alphabetagamma'
- Source then immediately restarts at generation (1, 0)
- The `evaluate_node` while-True loop continues instead of waiting
- This suggests something is resuming the source's task after it yields `WaitForStartNextGenerationCommand`

**Hypothesis**: When consumers complete, they call `_enqueue_output_nodes()`, which may be inadvertently triggering the source to restart. The resolution queue or `_find_node_solution` logic may be resuming nodes that should remain waiting.

**Next Steps Needed**:
1. Add logging around `WaitForStartNextGenerationCommand` handling to see what triggers node resumption
2. Investigate if `_enqueue_output_nodes` is enqueueing nodes that shouldn't be enqueued after completion
3. Check if the resolution queue closing logic is working correctly when all nodes complete
4. May need to add explicit "flow complete" detection to prevent restarting completed nodes

## Test Results
- **With Fix**: Consumers correctly get all chunks and detect stream completion
- **Remaining Issue**: Flow doesn't exit after completion, source restarts indefinitely
- **Full Test Suite**: 222 tests pass, 1 fails (the concurrency test), 1 skipped, 8 deselected

## Files Modified
- `src/flowno/core/node_base.py`: Parent generation check before stalling
- `src/flowno/core/flow/flow.py`: Minor cleanup of debug code

## Commits
- `67cceba`: WIP: Fix stream completion detection - check parent gen before stalling
- `aa0e978`: fix: Check parent generation before stalling in stream iteration

## Time Spent
Approximately 25-30 minutes of investigation and partial fix implementation.
