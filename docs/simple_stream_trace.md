# Simple Stream Deadlock - Behavioral Trace

## Overview

This document traces the execution of `examples/simple_stream_deadlock.py` to understand why streaming deadlocks after the first token.

**Graph Structure**:
```
Producer (async generator) --> Consumer (stream_in)
         yields strings         accumulates uppercase
```

**Expected Behavior**: Producer yields 3 tokens → Consumer reads all 3 → Returns accumulated result

**Actual Behavior**: Producer yields token 1 → Consumer reads it → Producer yields token 2 → **Consumer never reads token 2** → DEADLOCK

---

## Initial Setup

### Flow Construction

```python
# From examples/simple_stream_deadlock.py:120-122
with FlowHDL() as f:
    f.producer = Producer()
    f.consumer = Consumer(f.producer)
```

**State after construction**:
```
Producer.generation = None
Consumer.generation = None

Consumer._input_ports[0] = InputPort(node=Producer, port_index=0)
# Consumer expects a stream from Producer
```

### Flow Initialization

When `f.run_until_complete()` is called (line 128):

1. **Event loop starts** - `flow.py:1373-1380`
2. **Initial nodes enqueued** - nodes with no unresolved inputs
3. **Producer is ready** - no inputs, can start immediately
4. **Consumer is NOT ready** - waiting for Producer's stream data

**Resolution Queue**: `[Producer]`

---

## STEP 1: Producer First Execution - Yield Token 1

### 1a. Producer task starts

Producer is dequeued from resolution queue and executed:

```python
# From flow.py:586-637, evaluate_node() function
async def evaluate_node(node):
    while True:
        # Wait for signal to start next generation
        await _wait_for_start_next_generation(node, 0)

        # Call the node's function
        returned = node.coro_fn(*args, **kwargs)

        # Handle based on type
        if inspect.isasyncgen(returned):
            await self._handle_async_generator_node(node, returned)
```

Producer is an async generator, so it goes to `_handle_async_generator_node`:

```python
# From flow.py:441-583
async def _handle_async_generator_node(self, node, returned):
    while True:
        try:
            result = await anext(returned)  # Producer yields "hello"
```

### 1b. Producer yields first token

```python
# Producer code:
yield "hello"  # First token
```

This returns to `_handle_async_generator_node` (flow.py:480):

```python
# From flow.py:480-522
result = await anext(returned)  # result = "hello"

if not isinstance(result, tuple):
    result = (result,)  # result = ("hello",)

# Wait for previous streaming data to be consumed
await node._barrier1.wait()  # Barrier initialized to 0, passes immediately

# Push streaming data (run_level=1)
node.push_data(result, 1)
```

### 1c. Push streaming data

```python
# From node_base.py:563-572
def push_data(self, data, run_level=1):
    new_generation = inc_generation(self.generation, run_level)
    # Producer.generation = None
    # inc_generation(None, 1) = (0, 0)  # From helpers.py:134-156

    self.generation = (0, 0)
    self._data[(0, 0)] = ("hello",)
```

**STATE**:
```
Producer.generation = (0, 0)
Producer._data = {(0, 0): ("hello",)}
```

### 1d. Set barrier and enqueue consumers

```python
# From flow.py:517-522
node._barrier1.set_count(len(node.get_output_nodes_by_run_level(1)))
# Consumer consumes at run_level=1, so count=1

await self._enqueue_output_nodes(node)  # Enqueue Consumer
```

**STATE**:
```
Producer._barrier1.count = 1  # Waiting for Consumer to read
Resolution Queue: [Consumer]
```

Producer's task is now **waiting at `await node._barrier1.wait()`** (line 528) to be woken when Consumer reads the data.

---

## STEP 2: Consumer First Execution - Read Token 1

### 2a. Consumer task starts

Consumer is dequeued and executed:

```python
# Consumer code executes
async for token in input_stream:
    # This calls input_stream.__anext__()
```

### 2b. Stream.__anext__() delegates to _stream_get()

```python
# From node_base.py:810-818
async def __anext__(self) -> _InputType:
    try:
        result = yield from _stream_get(self)
        return result
```

### 2c. _stream_get() yields StreamGetCommand

**SIMPLIFIED IMPLEMENTATION** (node_base.py:827-832):

```python
@coroutine
def _stream_get(stream: "Stream[_T]") -> Generator[StreamGetCommand[_T], _T | None, _T]:
    """Get the next value from a stream by deferring to the event loop."""
    logger.debug(f"_stream_get({stream}) called", extra={"tag": "flow"})
    return (yield StreamGetCommand(stream=stream, consumer_node=stream.input.node))
```

All stream logic is now in the event loop command handler.

### 2d. Event loop handles StreamGetCommand

**From flow.py:1134-1219**, the `StreamGetCommand` handler:

#### Get or create stream state:

```python
# Line 1141-1144
stream_state = self.flow._stream_consumer_state.get(stream)
if stream_state is None:
    stream_state = StreamConsumerState()
    self.flow._stream_consumer_state[stream] = stream_state
```

**Initial state**:
```python
stream_state.last_consumed_generation = None
stream_state.last_consumed_parent_generation = None
```

#### Check if stream is cancelled:

```python
# Line 1147-1151
if stream in self.flow._cancelled_streams.get(producer_node, set()):
    self.tasks.insert(0, (current_task, StreamCancelled(), None))
    return
```

Not cancelled, continue.

#### Calculate clipped stitched generation:

```python
# Line 1154-1158
input_port = stream.input
stitch_level = input_port.stitch_level_0
clipped_stitched = clip_generation(
    stitched_generation(producer_node.generation, stitch_level), 1
)
```

Let's evaluate:
- `producer_node.generation = (0, 0)`
- `stitch_level = 0` (no stitching needed, Producer has data)
- `stitched_generation((0, 0), 0) = (0, 0)` (from helpers.py:232-256)
- `clip_generation((0, 0), 1) = (0, 0)` (from helpers.py:49-55, keeps up to run_level 1)

**Result**: `clipped_stitched_gen = (0, 0)`

#### Check if data is ready:

```python
# Line 1162-1178
if cmp_generation(stream_state.last_consumed_generation, clipped_stitched_gen) >= 0:
    # Data not ready, stall consumer
```

Evaluation:
- `stream_state.last_consumed_generation = None`
- `cmp_generation(None, (0, 0)) = -1` (from helpers.py:102-130, None is "older" than any generation)

Since `-1 >= 0` is False, **data IS ready**. Skip the stall block.

#### Check if stream is complete:

```python
# Line 1182-1195
parent_clipped_stitched = parent_generation(clipped_stitched_gen)
# parent_generation((0, 0)) = (0,)  # From helpers.py:16-26

if cmp_generation(stream_state.last_consumed_parent_generation, parent_clipped_stitched) >= 0:
    # Stream complete, raise StopAsyncIteration
```

Evaluation:
- `stream_state.last_consumed_parent_generation = None`
- `cmp_generation(None, (0,)) = -1`

Since `-1 >= 0` is False, **stream NOT complete**. Continue reading.

#### Extract data and update state:

```python
# Line 1197-1204
data = producer_node._data[clipped_stitched_gen]  # ("hello",)

stream_state.last_consumed_generation = clipped_stitched_gen  # (0, 0)
stream_state.last_consumed_parent_generation = parent_clipped_stitched  # (0,)
```

**STATE AFTER FIRST READ**:
```
stream_state.last_consumed_generation = (0, 0)
stream_state.last_consumed_parent_generation = (0,)
```

#### Countdown Producer's barrier:

```python
# Line 1209-1211
with get_current_flow_instrument().on_barrier_node_read(producer_node, 1):
    self.tasks.insert(0, (producer_node._barrier1.count_down(exception_if_zero=True), None, None))
```

This decrements `Producer._barrier1.count` from 1 to 0, **unblocking Producer**.

#### Resume consumer with data:

```python
# Line 1213
self.tasks.insert(0, (current_task, data[0], None))  # Resume with "hello"
```

Consumer receives "hello", prints "got token #1: 'hello'", and loops back to `async for token in input_stream`.

---

## STEP 3: Producer Second Execution - Yield Token 2

Producer's barrier has been counted down, so it's unblocked and continues:

```python
# From flow.py:528-530
await node._barrier1.wait()  # Now unblocked!

# Wait for permission to continue to next generation
await _wait_for_start_next_generation(node, 1)
```

After `_wait_for_start_next_generation` is handled, the loop continues:

```python
# Back at flow.py:469
while True:
    result = await anext(returned)  # Producer yields "world"
```

### 3a. Producer yields second token

```python
yield "world"  # Second token
```

### 3b. Push streaming data

```python
# From flow.py:507-522
node.push_data(("world",), 1)
```

```python
# From node_base.py:563-572
def push_data(self, data, run_level=1):
    new_generation = inc_generation(self.generation, run_level)
    # Producer.generation = (0, 0)
    # inc_generation((0, 0), 1) = (0, 1)  # From helpers.py:134-156

    self.generation = (0, 1)
    self._data[(0, 1)] = ("world",)
```

**STATE**:
```
Producer.generation = (0, 1)
Producer._data = {(0, 0): ("hello",), (0, 1): ("world",)}
```

### 3c. Set barrier and enqueue consumers

```python
# From flow.py:517-522
node._barrier1.set_count(1)  # Consumer should read this

await self._enqueue_output_nodes(node)  # Enqueue Consumer
```

**STATE**:
```
Producer._barrier1.count = 1  # Waiting for Consumer to read token 2
Resolution Queue: [Consumer] (if not already running)
```

Producer waits at barrier again.

---

## STEP 4: Consumer Second Read - **THE DEADLOCK**

Consumer loops back to:

```python
async for token in input_stream:
    # Calls input_stream.__anext__() again
```

### 4a. _stream_get() yields StreamGetCommand again

Same as before:

```python
return (yield StreamGetCommand(stream=stream, consumer_node=stream.input.node))
```

### 4b. Event loop handles StreamGetCommand (SECOND TIME)

#### Get stream state (now has history):

```python
stream_state = self.flow._stream_consumer_state.get(stream)
```

**Current state**:
```python
stream_state.last_consumed_generation = (0, 0)  # From first read
stream_state.last_consumed_parent_generation = (0,)
```

#### Calculate clipped stitched generation:

```python
producer_node.generation = (0, 1)  # Producer advanced!
stitch_level = 0
clipped_stitched_gen = clip_generation(stitched_generation((0, 1), 0), 1)
# = clip_generation((0, 1), 1)
# = (0, 1)
```

**Wait, let's double-check this calculation!**

From helpers.py:232-256, `stitched_generation`:

```python
def stitched_generation(generation, stitch_level):
    if generation is None:
        if stitch_level == 0:
            return None
        else:
            return (0,) * stitch_level
    else:
        # generation is not None
        return generation  # NO STITCHING, just return as-is
```

So: `stitched_generation((0, 1), 0) = (0, 1)`

From helpers.py:49-55, `clip_generation`:

```python
def clip_generation(generation: Generation, run_level: int) -> Generation:
    if generation is None:
        return None
    return generation[:run_level + 1]  # Keep elements up to index run_level
```

So: `clip_generation((0, 1), 1) = (0, 1)[:2] = (0, 1)`

**Result**: `clipped_stitched_gen = (0, 1)` ✓

#### Check if data is ready:

```python
# Line 1162-1178
if cmp_generation(stream_state.last_consumed_generation, clipped_stitched_gen) >= 0:
    # Data not ready, STALL consumer
```

**THIS IS THE CRITICAL CHECK!**

Evaluation:
- `stream_state.last_consumed_generation = (0, 0)`
- `clipped_stitched_gen = (0, 1)`
- `cmp_generation((0, 0), (0, 1)) = ?`

From helpers.py:102-130, `cmp_generation`:

```python
def cmp_generation(a: Generation, b: Generation) -> int:
    # Neither is None
    # Compare lexicographically
    if a < b:
        return -1
    elif a > b:
        return 1
    else:
        return 0
```

Lexicographic comparison:
- `(0, 0) < (0, 1)` → Compare element by element: 0 == 0, then 0 < 1
- Result: `(0, 0) < (0, 1)` is **True**

So: `cmp_generation((0, 0), (0, 1)) = -1`

Evaluation: `-1 >= 0` is **False**

**Data IS ready!** So we should NOT stall.

Wait, but the test shows it deadlocks! Let me re-check the test output more carefully...

Actually, looking at the test output again, maybe the issue is different. Let me add more detailed logging to see exactly what's happening in the StreamGetCommand handler.

---

## Hypothesis: The Issue

Based on code analysis, the data readiness check should pass:
- `cmp_generation((0, 0), (0, 1)) = -1`
- `-1 >= 0` is False
- Therefore, data should be ready and Consumer should read it

**But the test shows deadlock!** This suggests one of:

1. **The clipped_stitched_gen calculation is wrong** - maybe it's not advancing?
2. **The state is not being updated correctly** - maybe last_consumed_generation isn't (0, 0)?
3. **There's a race condition** - maybe Producer hasn't actually advanced when Consumer checks?
4. **The data isn't in _data dict** - maybe `Producer._data[(0, 1)]` doesn't exist?
5. **The barrier countdown logic is broken** - maybe Producer never gets unblocked after first read?

Let me check which hypothesis is correct by examining the actual test logs more carefully or adding instrumentation.

---

## Investigation Needed

To determine the exact failure mode, we need to add logging to:

1. **flow.py:1154-1158** - Log the calculated `clipped_stitched_gen`
2. **flow.py:1162** - Log the `last_consumed_generation` and comparison result
3. **flow.py:1197** - Log successful data extraction
4. **flow.py:1165-1176** - Log when consumer is stalled

Example instrumentation:

```python
logger.info(f"[STREAM_GET] producer.generation={producer_node.generation}, "
            f"last_consumed={stream_state.last_consumed_generation}, "
            f"clipped_stitched={clipped_stitched_gen}")

if cmp_generation(stream_state.last_consumed_generation, clipped_stitched_gen) >= 0:
    logger.info(f"[STREAM_GET] DATA NOT READY - stalling consumer")
    # ... stall logic
else:
    logger.info(f"[STREAM_GET] DATA READY - extracting data")
```

This would reveal exactly which part of the logic is failing.

---

## Additional Notes

### Why Did Old Implementation Work?

The old implementation (before simplification) had the stream consumption logic in a `while` loop inside the coroutine:

```python
# OLD CODE (removed)
while cmp_generation(stream_state.last_consumed_generation, clipped_stitched_gen) >= 0:
    # Stall and wait for data
    yield StalledNodeRequestCommand(...)
    # Loop back and check again
```

This would **loop repeatedly** checking for new data, whereas the new implementation only checks **once** per `StreamGetCommand`.

### Why New Implementation Might Fail

If the consumer checks before the producer has pushed the new data, the new implementation might:
1. See data not ready
2. Stall the consumer
3. **Never re-check** because no one enqueues the consumer again

The old loop-based approach would naturally re-check on the next iteration.

---

## Questions for Further Investigation

1. When Consumer is stalled (line 1165-1176), who is responsible for waking it up?
2. Is the stalled consumer added back to the resolution queue?
3. Does `_enqueue_output_nodes()` from Producer actually enqueue Consumer when it yields token 2?
4. Is there a timing issue where Consumer checks before Producer's state is updated?

---

## Next Steps

1. Add comprehensive logging to `StreamGetCommand` handler
2. Run `examples/simple_stream_deadlock.py` with logging
3. Examine exact state when deadlock occurs
4. Identify which assumption breaks down
