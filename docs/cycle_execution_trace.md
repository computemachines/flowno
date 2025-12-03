# Detailed Trace: Streaming Cycle Execution

## Graph Setup

```
A --(stream)--> B --(mono)--> A
```

- A produces stream output (async generator)
- B consumes A's stream, produces mono output
- A consumes B's mono output
- A has default value for input from B

## Initial State (Before Any Execution)

```
A.generation = None
B.generation = None
A._input_ports[0].stitch_level_0 = 0  # Input from B
B._input_ports[0].stitch_level_0 = 0  # Input from A (stream)

Resolution Queue: Empty
Unvisited: [A, B]  # or [B, A] - arbitrary order
```

---

## ITERATION 0, STEP 1: Initial Pull from Unvisited

**Action**: Main loop pops A from unvisited list, adds to resolution queue

```python
# From flow.py:848-853
while self.unvisited:
    initial_node = self.unvisited.pop(0)  # → A
    await self.resolution_queue.put(initial_node)
```

**State**:
```
Resolution Queue: [A]
Unvisited: [B]
```

---

## ITERATION 0, STEP 2: Process A from Resolution Queue

**Action**: Pull A from resolution queue, find solution

```python
# From flow.py:856-868
async for current_node in self.resolution_queue:  # → A
    solution_nodes = self._find_node_solution(current_node)
```

### Subanalysis: _find_node_solution(A)

#### 2a. Get stale inputs for A

```python
# From flow.py:882-886
def _find_node_solution(self, node):  # node = A
    supernode_root = self._condensed_tree(node)
```

```python
# From flow.py:963-976
def _condensed_tree(self, node):  # node = A
    # Get inputs that need data
    stale_inputs = node.get_inputs_with_le_generation_clipped_to_minimum_run_level()
```

**What is stale?**

For A's input from B:
- B.generation = None
- A's input has minimum_run_level = 0 (mono consumer)
- Clipped B generation: clip_generation(None, 0) = None
- Stitched: stitched_generation(None, stitch_level_0=0) = None
- Compare: cmp_generation(None, A.last_consumed_from_B=None)
  - From helpers.py:23-33, cmp_generation(None, None) = 0 (equal)

**Wait, that's equality, not less-than. Let me check the actual function:**

```python
# From node_base.py:596-628
def get_inputs_with_le_generation_clipped_to_minimum_run_level(self):
    stale_inputs = []
    for input_port_index, input_port in self._input_ports.items():
        if input_port.connected_output is None:
            continue

        upstream_node = input_port.connected_output.node
        upstream_gen = upstream_node.generation  # None for both A and B initially

        # Apply stitch
        stitch_0 = input_port.stitch_level_0  # = 0 initially
        stitched_gen = stitched_generation(upstream_gen, stitch_0)
        # stitched_generation(None, 0) = None (special case from helpers.py:253)

        # Clip to minimum run level
        clipped_gen = clip_generation(stitched_gen, input_port.minimum_run_level)
        # clip_generation(None, 0) = None

        # Get last consumed generation for this input
        last_consumed = self._data_generation.get(input_port_index)
        # For A initially: _data_generation is empty, so None

        # Compare: is upstream <= last_consumed?
        if cmp_generation(clipped_gen, last_consumed) <= 0:
            stale_inputs.append(input_port_index)

    return stale_inputs
```

**Key insight**: cmp_generation(None, None) = 0 (equal)
So condition `<= 0` is TRUE! Input IS stale!

**Result**: A's input from B is stale (because None <= None)

#### 2b. Build subgraph from stale inputs

```python
# From flow.py:977-986
for input_port_index in stale_inputs:  # [0] (input from B)
    upstream_node = node._input_ports[input_port_index].connected_output.node  # B

    # Check if this is a streaming connection
    is_streaming = node._input_ports[input_port_index].minimum_run_level > 0
    # A's input from B: minimum_run_level = 0 (mono), so is_streaming = False

    condensed_subgraph[node].add(input_port_index)  # A: {0}

    # Recurse on upstream
    condensed_subgraph.update(self._condensed_tree(upstream_node))  # _condensed_tree(B)
```

**Now recursively process B**:

For B's input from A:
- A.generation = None
- B's input has minimum_run_level = 1 (stream consumer)
- Clipped: clip_generation(stitched_generation(None, 0), 1) = None
- B's last_consumed = None
- cmp_generation(None, None) = 0, so <= 0 is TRUE
- **B's input from A is also stale**

So we get:
```python
condensed_subgraph = {
    A: {0},  # Input port 0 from B is stale
    B: {0}   # Input port 0 from A is stale
}
```

This is the full cycle! Both nodes need data from each other.

#### 2c. Find strongly connected components (Tarjan's algorithm)

```python
# From flow.py:1008-1061
sccs = self._tarjan_sccs(condensed_subgraph)
```

With cycle A ↔ B, Tarjan returns one SCC containing both:
```python
sccs = [[A, B]]  # One component
```

#### 2d. Build condensed tree (supernode graph)

```python
# From flow.py:1063-1086
condensed_tree = {}
for scc in sccs:
    # Create supernode for this SCC
    supernode = Supernode(members={})
    for node in scc:
        supernode.members[node] = condensed_subgraph[node]
```

Result:
```python
condensed_tree = {
    Supernode(members={A: {0}, B: {0}}): []  # No children (it's a leaf)
}
```

#### 2e. Find leaf supernodes

```python
# From flow.py:919-942
leaf_supernodes = self._find_leaf_supernodes(supernode_root)
```

Only one supernode, so:
```python
leaf_supernodes = [Supernode(members={A: {0}, B: {0}})]
```

#### 2f. Pick node to force evaluate

```python
# From flow.py:1088-1107
def _pick_node_to_force_evaluate(self, leaf_supernode):
    for node, input_ports in leaf_supernode.members.items():
        # Check if node has defaults for ALL stale inputs
        if all(node.has_default_for_input(input_port) for input_port in input_ports):
            return node
    raise MissingDefaultError(leaf_supernode)
```

Check A:
- A has stale input port 0 (from B)
- Does A have default for port 0? **YES** (given in problem)
- Return A

Check B:
- B has stale input port 0 (from A)
- Does B have default? Assuming NO (not specified)
- Don't return B

**Result**: solution_nodes = [A]

---

## ITERATION 0, STEP 3: Resume A

```python
# From flow.py:866-868
for leaf_node in solution_nodes:  # [A]
    self._mark_node_as_visited(leaf_node)
    await _resume_node(leaf_node)
```

### 3a. Mark A as visited

```python
# From flow.py:1109-1117
self.visited.add(A)
self.unvisited.remove(A) if A in self.unvisited else None
```

**State**:
```
Visited: [A]
Unvisited: [B]
```

### 3b. Resume A's persistent task

```python
# From flow.py:1119-1131
def _resume_node(node):
    yield from WaitForStartNextGenerationCommand(node, 0)
```

This wakes up A's evaluate_node task:

```python
# From flow.py:610
await _wait_for_start_next_generation(node, 0)  # Unblocks
```

### 3c. A gathers inputs

```python
# From flow.py:612-617
positional_arg_values, defaulted_inputs = node.gather_inputs()
```

```python
# From node_base.py:547-561
def gather_inputs(self):
    defaulted_inputs = []
    positional_arg_values = []

    for input_port_index, input_port in self._input_ports.items():
        # A has one input from B
        # B.generation is None, which is stale
        # Check get_inputs_with_le_generation...
        # Returns True (stale)

        # Use default value
        value = input_port.default_factory()
        positional_arg_values.append(value)
        defaulted_inputs.append(input_port_index)
```

**Result**:
```python
positional_arg_values = [default_value]
defaulted_inputs = [0]  # Port 0 used default
```

### 3d. Increment stitch_level_0 for defaulted inputs

```python
# From flow.py:614
await node.count_down_upstream_latches(defaulted_inputs)
```

```python
# From node_base.py:656-681
async def count_down_upstream_latches(self, defaulted_inputs):
    for input_port_index in defaulted_inputs:  # [0]
        input_port = self._input_ports[input_port_index]

        # THIS IS THE KEY: Increment stitch_level_0
        input_port.stitch_level_0 += 1  # Now = 1

        # Count down barrier if upstream exists
        upstream_node = input_port.connected_output.node  # B
        run_level = input_port.minimum_run_level  # 0

        # Count down B's barrier0
        yield from upstream_node._barrier0.count_down(exception_if_zero=True)
```

**CRITICAL STATE CHANGE**:
```
A._input_ports[0].stitch_level_0 = 1  # Was 0, now 1
```

This means: "Next time we check if B's data is stale for A, we'll add 1 to B's generation before comparing"

### 3e. Call A (it's an async generator)

```python
# From flow.py:618
returned = node.call(*positional_arg_values)  # async generator
```

A starts executing, yields first value.

```python
# From flow.py:629
await self._handle_async_generator_node(node, returned)
```

### 3f. Handle async generator - first iteration

```python
# From flow.py:441-583
async def _handle_async_generator_node(self, node, returned):
    acc = None

    try:
        while True:
            # Check for cancelled streams
            cancelled_streams = self._cancelled_streams.get(node, set())  # Empty

            # Run node's generator
            with get_current_flow_instrument().node_lifecycle(self, node, run_level=1):
                result = await anext(returned)  # A yields first value
```

Assume A yields: `"value_0_0"`

```python
            # Store as tuple
            if not isinstance(result, tuple):
                result = (result,)  # ("value_0_0",)

            # Accumulate for final return
            if acc is None:
                acc = result
            else:
                acc = tuple(a + b for a, b in zip(acc, result))

            # Push streaming data (run_level=1)
            node.push_data(result, 1)
```

### 3g. Push streaming data increments generation

```python
# From node_base.py:563-572
def push_data(self, data, run_level=1):
    new_generation = inc_generation(self.generation, run_level)
    # A.generation = None
    # inc_generation(None, 1) = (0, 0)  # From helpers.py:134-156

    self._data[tuple(new_generation)] = data
    # A._data = {(0, 0): ("value_0_0",)}
```

**STATE**:
```
A.generation = (0, 0)  # First streaming chunk at generation 0
```

### 3h. Set barrier and enqueue output nodes

```python
# From flow.py:501-522
# Remember how many output nodes consume at run_level=1
node._barrier1.set_count(len(node.get_output_nodes_by_run_level(1)))
# B is the only streaming consumer, so count=1

get_current_flow_instrument().on_node_emitted_data(self, node, result, 1)

await self._terminate_if_reached_limit(node)
await self._enqueue_output_nodes(node)  # Add B to queue
```

**STATE**:
```
Resolution Queue: [B]
A._barrier1.count = 1  # Waiting for 1 consumer to read
```

### 3i. Wait for barrier before next iteration

```python
# From flow.py:524-530
with get_current_flow_instrument().on_barrier_node_write(self, node, result, 1):
    await node._barrier1.wait()
```

**A BLOCKS HERE** waiting for B to read the data and countdown barrier1.

---

## ITERATION 0, STEP 4: Process B from Resolution Queue

**Action**: Main loop pulls B from queue

```python
async for current_node in self.resolution_queue:  # → B
    solution_nodes = self._find_node_solution(current_node)
```

### 4a. Find solution for B

Check B's stale inputs:
- B's input from A (port 0)
- A.generation = (0, 0)
- Stitch: stitched_generation((0, 0), B._input_ports[0].stitch_level_0=0) = (0, 0)
- Clip: clip_generation((0, 0), minimum_run_level=1) = (0, 0)
- B's last consumed from A: None (never consumed)
- Compare: cmp_generation((0, 0), None) = 1 (greater)
- **NOT stale!** (upstream > last_consumed)

**Result**:
```python
stale_inputs = []  # B has no stale inputs!
```

So condensed_subgraph is empty for B, meaning B is ready to run.

```python
solution_nodes = [B]
```

### 4b. Resume B

B's task wakes up at:

```python
# From flow.py:610
await _wait_for_start_next_generation(node, 0)  # Unblocks
```

### 4c. B gathers inputs

```python
positional_arg_values, defaulted_inputs = node.gather_inputs()
```

For B's input from A:
- It's a stream (minimum_run_level=1)
- Creates Stream object:

```python
# From node_base.py:707-713
if input_port.minimum_run_level > 0:  # Stream consumer
    inputs[input_port_index] = Stream(
        self.input(input_port_index),
        input_port.connected_output
    )
```

**Result**:
```python
stream_from_A = Stream(
    input=B.input(0),
    output=A.output(0)
)
positional_arg_values = [stream_from_A]
defaulted_inputs = []  # No defaults used
```

### 4d. Call B with stream

Assume B's implementation:

```python
@node(stream_in=["input_stream"])
async def B(input_stream: Stream):
    # Consume one item from stream
    value = await input_stream.__anext__()
    return value
```

When B calls `await input_stream.__anext__()`, it invokes Stream's `__anext__`:

```python
# From node_base.py:809-812
async def __anext__(self):
    return await self._stream_get()
```

### 4e. Stream._stream_get() execution (SIMPLIFIED IN CURRENT CODE)

**NOTE**: The old implementation (pre-simplification) had all stream logic inside `_stream_get()`.
That implementation included: state tracking, generation comparisons, stalling logic, barrier countdown,
and stream completion detection. **This was deemed too complex and has been removed.**

**Current (Simplified) Implementation**:

```python
# From node_base.py:827-832 (CURRENT - SIMPLIFIED)
@coroutine
def _stream_get(stream: "Stream[_T]") -> Generator[StreamGetCommand[_T], _T | None, _T]:
    """Get the next value from a stream by deferring to the event loop."""

    logger.debug(f"_stream_get({stream}) called", extra={"tag": "flow"})
    return (yield StreamGetCommand(stream=stream, consumer_node=stream.input.node))
```

When B calls `await input_stream.__anext__()`, it eventually calls `_stream_get()` which:
1. Creates a `StreamGetCommand`
2. **Yields it to the event loop** (delegates everything to FlowEventLoop)
3. Waits to be resumed with data

The event loop receives this command and handles it in `FlowEventLoop._handle_command()`:

```python
# From flow.py:1134-1219 (StreamGetCommand handler)
elif isinstance(command, StreamGetCommand):
    stream = command.stream  # Stream(B.input(0), A.output(0))
    consumer_node = command.consumer_node  # B
    current_task = current_task_packet[0]  # B's task
```

#### Get or create stream consumer state

```python
# From flow.py:1141-1144
if stream not in self.flow._stream_consumer_state:
    self.flow._stream_consumer_state[stream] = StreamConsumerState()

state = self.flow._stream_consumer_state[stream]
```

**STATE**:
```python
state.last_consumed_generation = None
state.last_consumed_parent_generation = None
state.cancelled = False
```

**Key difference from old code**: State is now keyed by Stream object directly, not (node, port_index) tuple.

#### Check if stream is cancelled

```python
# From flow.py:1147-1151
producer_node = stream.output.node  # A
if stream in self.flow._cancelled_streams.get(producer_node, set()):
    # Not cancelled in this case
    pass
```

#### Calculate clipped stitched generation

```python
# From flow.py:1154-1158
stitch_0 = stream.input.node._input_ports[stream.input.port_index].stitch_level_0
# B._input_ports[0].stitch_level_0 = 0

clipped_stitched_gen = clip_generation(
    stitched_generation(stream.output.node.generation, stitch_0),
    run_level=stream.run_level
)
# stitched_generation(A.generation=(0,0), stitch=0) = (0, 0)
# clip_generation((0, 0), run_level=1) = (0, 0)
```

**Result**: clipped_stitched_gen = (0, 0)

#### Check if data is ready

```python
# From flow.py:1162-1178
if cmp_generation(clipped_stitched_gen, state.last_consumed_generation) <= 0:
    # cmp_generation((0, 0), None) = 1 (greater than None)
    # 1 <= 0 is FALSE - data IS ready!
    # SKIP THIS BLOCK
```

**Old implementation note**: The old code had a `while` loop here that would stall and yield `StalledNodeRequestCommand`.
**This has been removed** - now it's a single `if` check that either stalls immediately or continues.

Data IS ready, so we skip the stalling block and continue:

#### Check if parent generation changed (stream complete)

```python
# From flow.py:1182-1195
current_parent_gen = parent_generation(stream.output.node.generation)
# parent_generation((0, 0)) = (0,)

if (state.last_consumed_generation is not None and
    current_parent_gen != state.last_consumed_parent_generation):
    # state.last_consumed_generation = None, so condition FALSE
    # Stream not complete yet - continue
```

#### Update state and read data

```python
# From flow.py:1197-1204
state.last_consumed_generation = clipped_stitched_gen  # (0, 0)
state.last_consumed_parent_generation = current_parent_gen  # (0,)

# Get the data
data_tuple = stream.output.node.get_data(run_level=stream.run_level)
# A._data[(0, 0)] = ("value_0_0",)
assert data_tuple is not None
data = data_tuple[stream.output.port_index]  # "value_0_0"
```

**STATE UPDATE**:
```python
state.last_consumed_generation = (0, 0)
state.last_consumed_parent_generation = (0,)
```

#### Count down barrier (NEW LOCATION)

```python
# From flow.py:1209-1211
with get_current_flow_instrument().on_barrier_node_read(producer_node, 1):
    self.tasks.insert(0, (producer_node._barrier1.count_down(exception_if_zero=True), None, None))
```

**Key difference from old code**: Barrier countdown is now done **directly by the event loop**, not by yielding
from the coroutine. The old code had `yield from stream.output.node._barrier1.count_down()`. Now the event
loop inserts the countdown coroutine as a task.

**This unblocks A!** A was waiting at barrier1.wait(), now count goes 1 → 0, A can continue.

#### Resume consumer with data

```python
# From flow.py:1216-1218
# Resume consumer task with the data
self.tasks.append((current_task, data, None))
return True
```

The event loop appends B's task back to the task queue, this time with `data="value_0_0"` to be sent into the coroutine.

**Result**: B's `await input_stream.__anext__()` completes and receives "value_0_0"

### 4f. B completes and returns

Assume B just returns the value:

```python
return value  # "value_0_0"
```

This is a coroutine (not async generator), so:

```python
# From flow.py:627
await self._handle_coroutine_node(node, returned)
```

```python
# From flow.py:420-438
async def _handle_coroutine_node(self, node, returned):
    result = await returned  # "value_0_0"

    if not isinstance(result, tuple):
        result = (result,)  # ("value_0_0",)

    # Wait for previous data to be consumed
    await node._barrier0.wait()

    # Push final data (run_level=0)
    node.push_data(result, 0)
```

Push data:

```python
# From node_base.py:563-572
def push_data(self, data, run_level=0):
    new_generation = inc_generation(self.generation, run_level)
    # B.generation = None
    # inc_generation(None, 0) = (0,)  # From helpers.py:134-156

    self._data[(0,)] = ("value_0_0",)
```

**STATE**:
```
B.generation = (0,)
B._data = {(0,): ("value_0_0",)}
```

Set barrier:

```python
# From flow.py:433-437
node._barrier0.set_count(len(node.get_output_nodes_by_run_level(0)))
# A consumes at run_level=0, so count=1
```

Enqueue output nodes:

```python
# From flow.py:637 (in finally)
await self._enqueue_output_nodes(node)  # Add A to queue
```

**STATE**:
```
Resolution Queue: [A]
B._barrier0.count = 1  # Waiting for A to read
```

---

## ITERATION 0, STEP 5: A Continues After Barrier Unblocked

Back in A's async generator handler, after barrier1.wait() returned:

```python
# From flow.py:530
await _wait_for_start_next_generation(node, 1)
```

This yields WaitForStartNextGenerationCommand, asking to continue to next streaming iteration.

The event loop handles this and resumes A, which loops back to:

```python
# From flow.py:469
while True:
    # Check cancelled streams - none

    # Get next value from generator
    result = await anext(returned)  # A yields second value
```

Assume A yields: `"value_0_1"`

Push streaming data:

```python
node.push_data(("value_0_1",), 1)
# inc_generation((0, 0), 1) = (0, 1)
# A.generation = (0, 1)
```

**STATE**:
```
A.generation = (0, 1)
A._data = {(0, 0): ("value_0_0",), (0, 1): ("value_0_1",)}
```

Enqueue output nodes again:

```python
await self._enqueue_output_nodes(node)  # Add B
```

**But wait!** This is where the skip logic used to matter (now simplified). Let's check:

```python
# CURRENT SIMPLIFIED CODE (flow.py:702-721)
for output_node in all_output_nodes:  # [B]
    # TODO: Add skip logic for streaming consumers
    nodes_to_enqueue.append(output_node)
```

**HISTORICAL CONTEXT**: The old implementation had complex skip logic here (lines 725-736 in previous version):
- Checked if output_node is a streaming consumer
- Checked generation comparisons: `output_node.generation >= source_node.generation`
- If conditions met, skipped enqueueing the node
- This logic was deemed too complex and removed

**CURRENT BEHAVIOR**: All output nodes are always enqueued (simple approach)

**Result**: B gets enqueued

But B is currently in the middle of processing! What happens?

Actually, B already consumed the first item and returned. B's task is now at:

```python
# From flow.py:610 (back at top of evaluate_node while loop)
await _wait_for_start_next_generation(node, 0)  # BLOCKED
```

B is waiting for next generation signal. Adding B to resolution queue will eventually resume it when processed.

---

This is getting very long. The pattern continues:

1. A yields more streaming values
2. Each time it enqueues B
3. B needs to consume all streaming values before A completes
4. When A completes (StopAsyncIteration), it pushes final run_level=0 data
5. A enqueues B again for next iteration
6. B reads A's new run_level=0 data
7. Cycle continues...

## KEY FINDINGS

### Stitch Level Behavior

When A uses default for input from B:
```
B.generation = None
A._input_ports[0].stitch_level_0 = 0 → 1

Next check for staleness:
stitched_generation(None, 1) = (0,)  # Special case from helpers.py:253
```

This makes B look like it has generation (0,) even though it's actually None. This prevents A from re-requesting B immediately.

### The Simplified Enqueue Logic (Current State)

**CURRENT IMPLEMENTATION** (flow.py:702-721):

```python
for output_node in all_output_nodes:
    # TODO: Add skip logic for streaming consumers
    nodes_to_enqueue.append(output_node)
```

All output nodes are always enqueued. No skip logic.

**HISTORICAL CONTEXT - The Problem with Old Skip Logic**:

The previous implementation checked whether to enqueue B after A produces streaming data:

```python
# OLD CODE (now removed)
if cmp_generation(B.generation, A.generation) >= 0:
    skip_enqueue()
```

This compared **node generations**, not **consumption state**.

After A cancels stream and returns new value:
- A advances to gen=(1,)
- B completes at gen=(0,)
- Skip logic sees B.gen=(0,) < A.gen=(1,), so tries to enqueue
- But deadlock could occur in certain circular dependency scenarios

**BETTER APPROACH (for future implementation)**:

Check per-edge consumption state instead of node generations:

```python
stream_state = flow._stream_consumer_state.get(stream_object)
if stream_state.last_consumed_generation >= producer_node.generation:
    skip_enqueue()  # Consumer has already consumed producer's latest
```

This directly checks: "Has the consumer consumed the producer's current data?" instead of comparing node generations.

Note: The system already tracks per-stream consumption state in `_stream_consumer_state` (keyed by Stream object), which is updated in the `StreamGetCommand` handler (flow.py:1197-1204).
