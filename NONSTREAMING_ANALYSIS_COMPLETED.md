# Comprehensive Analysis Completion: Flowno Nonstreaming Flows

This document provides definitive answers to all questions and uncertainties identified in the original NONSTREAMING_ANALYSIS.md, based on examination of the actual codebase.

---

## Section 1: Generation System

### Q1: What does a Generation tuple actually represent?

**Answer**: A Generation tuple is a hierarchical version identifier where each position represents a different "run level" of execution depth. Position 0 tracks main execution count, and subsequent positions track streaming/nested execution iterations within that main execution.

**Evidence**:
- File: `src/flowno/utilities/helpers.py`, Lines 1-30 (docstring)
- Code snippet:
```python
Generation tuples are ordered sequences of integers (e.g., (0,), (1, 0), (2, 1, 3))
that version the data produced by nodes. Each position represents a different
run level, where:
- The first element (main_gen) tracks the primary execution count
- Later elements track nested levels for streaming or partial results
```

**Explanation**: The generation tuple `(2, 1, 3)` means: main execution #2, first streaming level produced 1 items, second streaming level produced 3 items. For nonstreaming nodes, only the first element matters, so generations are typically `(0,)`, `(1,)`, `(2,)`, etc.

**Confidence**: HIGH

---

### Q2: What is "run level" and how does it differ for nonstreaming vs streaming nodes?

**Answer**: Run level is an index into the generation tuple. Run level 0 represents "final" or "complete" data from a node. Run levels 1+ represent progressively more granular streaming/partial results. Nonstreaming nodes only produce data at run level 0.

**Evidence**:
- File: `src/flowno/core/types.py`, Lines 1-5
- Code snippet:
```python
RunLevel: TypeAlias = Literal[0, 1, 2, 3]
```
- File: `src/flowno/core/flow/flow.py`, Lines 310-330 (`_handle_coroutine_node`)
```python
# For nonstreaming nodes:
node.push_data(result, 0)  # Always run_level=0
node._barrier0.set_count(len(node.get_output_nodes_by_run_level(0)))
```

**Explanation**: 
- **Nonstreaming nodes**: Always `push_data(..., run_level=0)`, produce tuples like `(0,)`, `(1,)`, `(2,)`
- **Streaming nodes**: First yield `push_data(..., run_level=1)` producing `(0, 0)`, `(0, 1)`, etc., then final value at run_level=0

**Confidence**: HIGH

---

### Q3: Why is `(0,) > (0, 0)` in the generation comparison? What is the semantic purpose?

**Answer**: Shorter tuples represent "more final" or "more complete" data. `(0,)` is a run_level=0 result (final), while `(0, 0)` is a run_level=1 result (streaming partial). The ordering ensures final data is considered "newer" than any partial data from the same main execution.

**Evidence**:
- File: `src/flowno/utilities/helpers.py`, Lines 35-70 (`cmp_generation` function)
```python
# Rule 2: If one tuple is shorter, it's considered "greater" (more final result)
if len(gen_a) < len(gen_b):
    return 1  # Shorter tuple (final result) comes after longer tuple (partial result)
elif len(gen_a) > len(gen_b):
    return -1  # Longer tuple (partial result) comes before shorter tuple (final result)
```

**Explanation**: This design choice means that when a streaming node finishes (producing final `(N,)` after streaming `(N, 0)`, `(N, 1)`, etc.), consumers waiting for final data will see the final result as "newer" than any streaming chunks.

**Confidence**: HIGH

---

### Q4: How does the generation increment algorithm work and why does run_level parameter matter?

**Answer**: `inc_generation(gen, run_level)` computes the minimal generation greater than `gen` that has length `run_level + 1`. The run_level parameter determines which "depth" of the tuple to increment.

**Evidence**:
- File: `src/flowno/utilities/helpers.py`, Lines 75-125 (`inc_generation` function)
```python
def inc_generation(gen, run_level=0):
    if gen is None:
        return (0,) * (run_level + 1)  # First generation at this run level
    else:
        # ...
        # For run_level=0: (0,) → (1,)
        # For run_level=1 from (1,): must produce (2, 0) because (1, 0) < (1,)
```

**Examples from docstring**:
```python
inc_generation(None, 0) → (0,)        # First gen at run level 0
inc_generation((0,), 0) → (1,)        # Increment run level 0
inc_generation((1,), 1) → (2, 0)      # Must increment main gen since (1, 0) < (1,)
inc_generation((1, 0), 1) → (1, 1)    # Increment run level 1
```

**Explanation**: The algorithm finds the minimal generation greater than `gen` according to `cmp_generation`. For streaming nodes at run_level=1, this means incrementing the streaming counter. When starting a new stream after a final value, the main generation must increment.

**Confidence**: HIGH

---

### Q5: What is the purpose of clip_generation() and what contract does it establish?

**Answer**: `clip_generation(gen, run_level)` returns the highest generation ≤ `gen` that has length at most `run_level + 1`. It determines what data version a consumer at a given run_level should read from a producer.

**Evidence**:
- File: `src/flowno/utilities/helpers.py`, Lines 130-185 (`clip_generation` function)
```python
def clip_generation(gen: Generation, run_level: int) -> Generation:
    """
    Clip a generation tuple to be compatible with a specific run level.
    
    Returns the "highest" generation (according to cmp_generation) that is
    less than or equal to gen and has a length of at most run_level + 1.
    """
```

**Examples from docstring**:
```python
clip_generation((0, 0), 0) → None     # No compatible generation exists
clip_generation((1, 0), 0) → (0,)     # Clipped to run_level 0
clip_generation((1, 0), 1) → (1, 0)   # Already compatible
```

**Contract**: If consumer requires run_level=0 data, it can only see final results. If producer has `(1, 2)` (streaming chunk), clipping to run_level=0 returns `(0,)` - the last final value, not the streaming chunks.

**Confidence**: HIGH

---

### Q6: How does the stitch_level mechanism work in cycle breaking?

**Answer**: When a node uses a default value for a cyclic input, `stitch_level_0` is incremented for that input port. The stitched_generation adds this value to the first element of producer's generation when checking staleness, making the producer appear "older" and thus triggering re-execution.

**Evidence**:
- File: `src/flowno/utilities/helpers.py`, Lines 215-240 (`stitched_generation` function)
```python
def stitched_generation(gen: Generation, stitch_0: int) -> Generation:
    """
    Apply a "stitch" adjustment to a generation tuple.
    Used for cycle breaking in dataflow graphs.
    """
    if gen is None:
        if stitch_0 != 0:
            return (stitch_0 - 1,)
        else:
            return None
    # ...
    list_gen = list(gen)
    list_gen[0] += stitch_0
    return tuple(list_gen)
```

- File: `src/flowno/core/flow/flow.py`, Lines 274-285 (`set_defaulted_inputs`)
```python
def set_defaulted_inputs(self, node, defaulted_inputs):
    self._defaulted_inputs[node] = defaulted_inputs
    for input_port_index in defaulted_inputs:
        node._input_ports[input_port_index].stitch_level_0 += 1
```

**Explanation**: In a cycle A→B→A, when A first runs with default (B hasn't run yet), stitch_level for that input increases. Next time staleness is checked, B's generation is "stitched" to appear one higher, ensuring A won't immediately re-use its default but will wait for fresh B data.

**Confidence**: HIGH

---

## Section 2: Node Definition & Decoration

### Q7: Is tuple wrapping always applied? What happens with multi-output nodes?

**Answer**: Yes, tuple wrapping is always applied for single-output nodes via `wrap_coroutine_tuple()`. Multi-output nodes (using `@node(multiple_outputs=True)`) skip wrapping because the user is expected to return a tuple directly.

**Evidence**:
- File: `src/flowno/decorators/single_output.py`, Lines 130-145
```python
def call(self, *args):
    result = func(*cast(Tuple[Unpack[Ts]], args))
    if isinstance(casted_result, Awaitable):
        return wrap_coroutine_tuple(casted_result)  # Wraps in tuple
    elif isinstance(result, AsyncGenerator):
        return wrap_async_generator_tuple(casted_result)  # Wraps in tuple
```

- File: `src/flowno/decorators/node.py`, Lines 195-200 (overloads show multi-output uses different path)
- File: `src/flowno/decorators/wrappers.py` contains the wrapping functions

**Explanation**: Single-output: `return 42` becomes `(42,)`. Multi-output: `return (a, b)` stays `(a, b)`. This uniformity lets the flow always treat node outputs as tuples regardless of declaration style.

**Confidence**: HIGH

---

### Q8: How are unconnected input ports handled? What exactly triggers MissingDefaultError?

**Answer**: Unconnected input ports require a default value. `MissingDefaultError` is raised in two scenarios: (1) during `gather_inputs()` when an unconnected port has no default, or (2) during cycle resolution when no node in a cycle has defaults for all its cycle-internal inputs.

**Evidence**:
- File: `src/flowno/core/node_base.py`, Lines 850-900 (`gather_inputs` method)
```python
if input_port.connected_output is None:
    if has_default:
        inputs[input_port_index] = input_port.default_value
        continue
    else:
        raise MissingDefaultError(self, input_port_index)
```

- File: `src/flowno/core/node_base.py`, Lines 1200-1230 (`MissingDefaultError` class)
```python
# For cycles (SuperNode case):
for node, internal_input_ports in node.members.items():
    for internal_input_port in internal_input_ports:
        if node.has_default_for_input(internal_input_port):
            continue
        else:
            # Add to missing_info
```

**Explanation**: The error message is informative - it shows which parameters need defaults and provides file/line information. For cycles, it shows all nodes in the cycle and which ONE of them needs defaults.

**Confidence**: HIGH

---

## Section 3: Input Resolution & Staleness

### Q9: How does the staleness check in get_inputs_with_le_generation_clipped_to_minimum_run_level() work?

**Answer**: For each connected input, the method clips the producer's generation to the consumer's minimum_run_level, adds the stitch value, and compares to the consumer's generation. If clipped+stitched ≤ consumer's gen, the input is "stale" and needs fresh data.

**Evidence**:
- File: `src/flowno/core/node_base.py`, Lines 700-750 (`get_inputs_with_le_generation_clipped_to_minimum_run_level`)
```python
for my_input_port_index, input_port in self._input_ports.items():
    # ...
    input_node = placeholder.node
    
    # Clip the input node's generation based on the minimum run level required.
    clipped_gen: Generation = clip_generation(input_node.generation, input_port.minimum_run_level)
    
    # Add the stitch value to the clipped generation.
    clipped_gen = stitched_generation(clipped_gen, input_port.stitch_level_0)
    
    # Compare the clipped generation with this node's current generation.
    # If clipped_gen <= self.generation, the input is stale.
    if cmp_generation(clipped_gen, self.generation) <= 0:
        stale_inputs.append(input_port)
```

**Explanation**: 
- "Stale" means: producer hasn't produced data that's newer than what consumer last consumed
- Clipping ensures nonstreaming consumers (min_run_level=0) only consider final data
- Stitching handles cycle-breaking scenarios

**Confidence**: HIGH

---

### Q10: What triggers a node to be marked as "Ready" vs "Stalled" vs "Running"?

**Answer**: 
- **Ready**: Node yielded `WaitForStartNextGenerationCommand` - waiting for scheduler
- **Running**: Node's task is actively executing (between wait and next yield)
- **Stalled**: Node yielded `StalledNodeRequestCommand` - blocked waiting for specific input data

**Evidence**:
- File: `src/flowno/core/flow/flow.py`, Lines 780-850 (`FlowEventLoop._handle_command`)
```python
if isinstance(command, WaitForStartNextGenerationCommand):
    node = command.node
    self.flow.set_node_status(node, NodeTaskStatus.Ready())
    # ...

elif isinstance(command, ResumeNodeCommand):
    # ...
    self.flow.set_node_status(node, NodeTaskStatus.Running())
    # ...

elif isinstance(command, StalledNodeRequestCommand):
    stalled_input = command.stalled_input
    self.flow.set_node_status(stalled_input.node, NodeTaskStatus.Stalled(stalled_input))
```

**Explanation**: Status transitions are command-driven. When a node's coroutine yields a command, the event loop handler updates status. This enables cooperative scheduling without preemption.

**Confidence**: HIGH

---

## Section 4: Synchronization & Barriers

### Q11: What is the actual purpose of CountdownLatch barriers (_barrier0, _barrier1)?

**Answer**: Barriers ensure a producer doesn't overwrite its output data until all consumers have read the previous value. `_barrier0` is for run_level=0 (final data), `_barrier1` is for run_level=1 (streaming data).

**Evidence**:
- File: `src/flowno/core/flow/flow.py`, Lines 305-330 (`_handle_coroutine_node`)
```python
async def _handle_coroutine_node(self, node, returned):
    result = await returned
    
    # Wait for the last output data to have been read before overwriting
    with get_current_flow_instrument().on_barrier_node_write(self, node, result, 0):
        await node._barrier0.wait()  # Block until all consumers counted down
    
    node.push_data(result, 0)  # Now safe to write
    
    # Remember how many times output data must be read
    node._barrier0.set_count(len(node.get_output_nodes_by_run_level(0)))
```

- File: `src/flowno/core/node_base.py`, Lines 980-1000 (`count_down_upstream_latches`)
```python
async def count_down_upstream_latches(self, defaulted_inputs):
    """Count down upstream node barriers for non-defaulted connected inputs."""
    for input_port_index, input_port in self._input_ports.items():
        if input_port.connected_output is None or input_port_index in defaulted_inputs:
            continue
        if input_port.minimum_run_level > 0:
            continue  # Streaming inputs handle their own countdown
        upstream_node = input_port.connected_output.node
        await upstream_node._barrier0.count_down(exception_if_zero=True)
```

**Explanation**: Producer writes → sets barrier count to N consumers → each consumer counts down after reading → when count reaches 0, producer can write next value. This prevents data races without locks.

**Confidence**: HIGH

---

### Q11b: How does the barrier countdown work exactly?

**Answer**: The CountdownLatch is initialized to 0, then set to N (consumer count) after producer writes. Each consumer counts it down after reading. When it reaches 0, producer can write again.

**Evidence**:
- File: `src/flowno/core/flow/flow.py`, Lines 305-330 (`_handle_coroutine_node`)
```python
# FIRST: Wait for previous data to be consumed (initial count is 0, so passes immediately on first run)
await node._barrier0.wait()

# THEN: Write new data
node.push_data(result, 0)

# FINALLY: Set up barrier for next round (N = number of run_level=0 consumers)
node._barrier0.set_count(len(node.get_output_nodes_by_run_level(0)))
```

- File: `src/flowno/core/node_base.py`, Lines 980-1000 (`count_down_upstream_latches`)
```python
# Called by consumer AFTER gathering inputs (after reading data)
for input_port_index, input_port in self._input_ports.items():
    if input_port.connected_output is None or input_port_index in defaulted_inputs:
        continue
    if input_port.minimum_run_level > 0:
        continue  # Streaming handles its own countdown in Stream.__anext__
    upstream_node = input_port.connected_output.node
    await upstream_node._barrier0.count_down(exception_if_zero=True)
```

**Lifecycle example for A→B→C (A has 2 consumers B and C)**:
1. A runs first time: `barrier0.wait()` passes (count=0), writes data, sets `count=2`
2. B reads A's data, calls `A._barrier0.count_down()` → count becomes 1
3. C reads A's data, calls `A._barrier0.count_down()` → count becomes 0
4. A tries to run again: `barrier0.wait()` passes (count=0), writes new data, sets `count=2`
5. ...repeat

**Key detail**: The countdown happens in `count_down_upstream_latches()` which is called in `evaluate_node()` AFTER `gather_inputs()` but BEFORE calling the node's function. This ensures the read is acknowledged before the consumer processes.

**Confidence**: HIGH

---

### Q12: Why does push_data() persist all generation tuples in _data dict instead of keeping only latest?

**Answer**: The dict structure allows different consumers to access data at different run levels independently. A streaming consumer might need `(1, 2)` while a nonstreaming consumer needs `(1,)`. Keeping all allows this flexibility.

**Evidence**:
- File: `src/flowno/core/node_base.py`, Lines 650-680 (`get_data` method)
```python
def get_data(self, run_level: RunLevel = 0) -> ReturnTupleT_co | None:
    if self.generation is None:
        return None
    if len(self.generation) - 1 > run_level:
        # Truncating is data in the future
        requested_generation = list(self.generation[: run_level + 1])
        requested_generation[run_level] -= 1
        if tuple(requested_generation) not in self._data:
            return None
        return self._data[tuple(requested_generation)]
    # ...
    return self._data[self.generation]
```

**Explanation**: The `_data` dict acts as a versioned store. While typically only the most recent per-run-level is accessed, the structure supports complex scenarios where multiple consumers at different run levels need different versions simultaneously.

**Note**: The comment "TODO: We only ever read the highest clipped generation data for each run level. Replace with a forgetful datastructure" suggests this is a known area for optimization.

**Confidence**: HIGH

---

## Section 5: Execution Flow & Scheduling

### Q13: Walk through the complete execution timeline for a simple 2-node flow (A → B)

**Answer**: Here is the definitive timeline:

```python
@node
async def A() -> int:
    return 1

@node
async def B(x: int) -> int:
    return x + 1

with FlowHDL() as f:
    f.a = A()
    f.b = B(f.a)

f.run_until_complete()
```

**Timeline with code references**:

1. **Construction Phase** (inside `with` block):
   - `A()` creates DraftNode instance, registered with FlowHDLView
   - `B(f.a)` creates DraftNode with input connected to A's output(0)
   - File: `src/flowno/core/node_base.py`, Lines 200-280 (`DraftNode.__init__`)

2. **Finalization** (FlowHDL `__exit__`):
   - All DraftNodes converted to FinalizedNodes
   - Placeholder references resolved to actual connections
   - Nodes registered with Flow via `_flow.add_node()`
   - File: `src/flowno/core/flow_hdl_view.py`

3. **Flow.run_until_complete()** called:
   - Sets `_current_flow` global
   - Calls `event_loop.run_until_complete(_node_resolve_loop(...))`
   - File: `src/flowno/core/flow/flow.py`, Lines 540-570

4. **_node_resolve_loop starts**:
   - Pops first unvisited node (A) and puts in resolution_queue
   - File: `src/flowno/core/flow/flow.py`, Lines 580-620

5. **Resolution loop iteration 1 (A)**:
   - Gets A from queue
   - `_find_node_solution(A)` → A has no stale inputs → returns [A]
   - `_mark_node_as_visited(A)` → registers A's task
   - `_resume_node(A)` → sets A to Running, schedules A's task
   - File: `src/flowno/core/flow/flow.py`, Lines 610-640

6. **A.evaluate_node() runs**:
   - `await _wait_for_start_next_generation(A, 0)` → yields command, scheduler marks Ready then Running
   - `gather_inputs()` → returns `((), [])` (empty args, no defaults)
   - `count_down_upstream_latches([])` → no-op
   - `A.call()` returns coroutine
   - `_handle_coroutine_node(A, coro)`:
     - `await coro` → result = `(1,)`
     - `await A._barrier0.wait()` → count is 0, passes immediately (first run)
     - `A.push_data((1,), 0)` → A.generation becomes `(0,)`
     - `A._barrier0.set_count(1)` → B is the one consumer at run_level=0
   - `_enqueue_output_nodes(A)` → puts B in resolution_queue
   - `await _wait_for_start_next_generation(A, 0)` → A becomes Ready
   - File: `src/flowno/core/flow/flow.py`, Lines 420-500

7. **Resolution loop iteration 2 (B)**:
   - Gets B from queue
   - `_find_node_solution(B)` → checks B's inputs:
     - A's generation `(0,)` clipped to run_level=0 = `(0,)`
     - B's generation = None
     - `cmp_generation((0,), None)` = 1 (A is newer) → A is NOT stale
   - Returns [B] (B can run)
   - `_resume_node(B)` → B runs

8. **B.evaluate_node() runs**:
   - `gather_inputs()`:
     - Gets A's data via `A.get_data(run_level=0)` → `(1,)`
     - Extracts port 0 → `1`
     - Returns `((1,), [])`
   - `count_down_upstream_latches([])`:
     - Counts down A._barrier0 (1 → 0)
   - `B.call(1)` returns coroutine
   - `_handle_coroutine_node(B, coro)`:
     - `await coro` → result = `(2,)`
     - `await B._barrier0.wait()` → passes (count=0)
     - `B.push_data((2,), 0)` → B.generation becomes `(0,)`
     - `B._barrier0.set_count(0)` → no downstream consumers
   - `_enqueue_output_nodes(B)` → nothing to enqueue
   - B becomes Ready

9. **Resolution loop exits**:
   - `resolution_queue` is empty
   - `running_nodes` is empty
   - Queue closed, loop terminates
   - File: `src/flowno/core/flow/flow.py`, Lines 800-810

10. **Data access**:
    - `f.b.get_data()` returns `(2,)`

**Confidence**: HIGH

---

### Q14: How does _enqueue_output_nodes() determine which downstream nodes to schedule?

**Answer**: It enqueues ALL nodes connected to any output port of the completing node, with a special optimization to skip streaming consumers that are already at the same/higher generation.

**Evidence**:
- File: `src/flowno/core/flow/flow.py`, Lines 460-510 (`_enqueue_output_nodes`)
```python
async def _enqueue_output_nodes(self, out_node):
    if not self.resolution_queue.closed:
        nodes_to_enqueue = []
        all_output_nodes = out_node.get_output_nodes()
        
        for output_node in all_output_nodes:
            # Check if this output node has a streaming connection
            is_streaming_consumer = False
            for input_port in output_node._input_ports.values():
                if (input_port.connected_output is not None and
                    input_port.connected_output.node is out_node and
                    input_port.minimum_run_level == 1):
                    is_streaming_consumer = True
                    break
            
            # For streaming consumers: skip if they're at same/higher generation
            if is_streaming_consumer and output_node in self.node_tasks:
                status = self.node_tasks[output_node].status
                if isinstance(status, NodeTaskStatus.Ready):
                    # ... generation comparison logic ...
                    continue
            
            nodes_to_enqueue.append(output_node)
        
        await self.resolution_queue.putAll(nodes_to_enqueue)
```

**Explanation**: Nonstreaming consumers are always enqueued. Streaming consumers may be skipped if they're already satisfied. The resolution loop then determines via `_find_node_solution` whether enqueued nodes actually need to run.

**Confidence**: HIGH

---

## Section 6: Edge Cases & Composition

### Q15: How do streaming inputs (minimum_run_level=1) compose with nonstreaming (return-based) outputs?

**Answer**: A node with streaming inputs iterates over the Stream object, which internally yields `StalledNodeRequestCommand` to wait for producer data. When the node `return`s (nonstreaming output), the iteration stops and final result is pushed at run_level=0.

**Evidence**:
- File: `src/flowno/core/node_base.py`, Lines 800-900 (`gather_inputs` and `Stream` class)
```python
# In gather_inputs():
if input_port.minimum_run_level > 0 and not this_port_defaulted:
    inputs[input_port_index] = Stream(self.input(input_port_index), input_port.connected_output)
else:
    inputs[input_port_index] = individual_last_data
```

- File: `src/flowno/core/node_base.py`, Lines 1050-1150 (`Stream.__anext__` and `_stream_get`)
```python
# Stream iteration logic
while cmp_generation(get_clipped_stitched_gen(), state.last_consumed_generation) <= 0:
    # Data not ready, stall
    yield from _node_stalled(stream.input, stream.output.node)

# Check for stream completion
current_parent_gen = parent_generation(stream.output.node.generation)
if (state.last_consumed_generation is not None
    and current_parent_gen != state.last_consumed_parent_generation):
    raise StopAsyncIteration
```

**Example**:
```python
@node(stream_in=["values"])
async def Sum(values: Stream[int]) -> int:
    total = 0
    async for v in values:  # Each iteration may stall waiting for producer
        total += v
    return total  # Final return pushed at run_level=0
```

**Explanation**: The Stream object wraps the iteration. Each `async for` iteration either returns available data or yields a stall command. When producer finishes (parent generation changes), `StopAsyncIteration` is raised, ending the loop. The `return` statement then triggers `_handle_coroutine_node` which pushes at run_level=0.

**Confidence**: HIGH

---

### Q16: How does placeholder resolution work in FlowHDL context exit?

**Answer**: When the FlowHDL context exits, `_finalize()` is called on all registered DraftNodes. Placeholders (NodePlaceholder and OutputPortRefPlaceholder) are resolved by looking up their names in the FlowHDL's attribute dictionary.

**Evidence**:
- File: `src/flowno/core/flow_hdl_view.py` (referenced but content not fully in XML)
- File: `src/flowno/core/node_base.py`, Lines 360-380 (`DraftInputPort._finalize`)
```python
def _finalize(self, port_index, final_by_draft):
    if isinstance(self.connected_output, OutputPortRefPlaceholder):
        raise AttributeError(
            "Attempted to finalize an input port, {self} that still has a placeholder connected_output."
        )
    
    if self.connected_output is None:
        finalized_connected_output = None
    else:
        finalized_connected_output = self.connected_output._finalize(final_by_draft)
    
    return FinalizedInputPort[_T](...)
```

- File: `src/flowno/core/node_base.py`, Lines 420-450 (`NodePlaceholder` class)
```python
@dataclass
class NodePlaceholder:
    """Placeholder for a node defined on a FlowHDL context instance."""
    name: str
    
    def output(self, output_port) -> "OutputPortRefPlaceholder[object]":
        return OutputPortRefPlaceholder[object](self, OutputPortIndex(output_port))
```

**Explanation**: 
1. During construction: `f.b = B(f.a)` → `f.a` returns `NodePlaceholder("a")`
2. Later: `f.a = A()` → stores actual DraftNode at attribute "a"
3. On exit: Finalization walks all DraftNodes, resolves placeholders by name lookup
4. `OutputPortRefPlaceholder` → looked up → DraftNode → `DraftOutputPortRef`

**Confidence**: MEDIUM (finalization code not fully visible in provided XML)

---

## Appendix A: Updated Confidence Levels

| Concept | Original Confidence | Updated Confidence | Change Reason |
|---------|--------------------|--------------------|---------------|
| **Generation** | High | HIGH | Confirmed by docstrings |
| **Run Level** | Medium | HIGH | Confirmed by code examination |
| **Staleness** | Low | HIGH | Full algorithm traced |
| **Default Value** | High | HIGH | Confirmed |
| **Barrier** | Low | HIGH | Purpose now fully understood |
| **Stitch Level** | Low | HIGH | Mechanism traced through code |
| **Clipping** | Low | HIGH | Contract clear from docstring |

---

## Appendix B: Corrected/Clarified Hypotheses

### Hypothesis 1: "None values are considered 'oldest'"
**Status**: CLARIFICATION NEEDED
**Truth**: The comparison semantics require careful interpretation:

```python
# From helpers.py:
if gen_a is None and gen_b is not None:
    # node_a has never been run, so is considered "newer"/"less final" than node_b
    return -1  # This means None < (0,) in comparison order
```

**Key Insight**: There are TWO ways to interpret this:
1. **Comparison order**: `None < (0,)` - None comes "before" in sorted order
2. **Data freshness**: None means "no data yet" which is semantically "less fresh" than having data

**Why this matters for staleness**: In the staleness check:
```python
if cmp_generation(producer_gen, consumer_gen) <= 0:  # producer is stale
```
- If producer has `None` (never run) and consumer has `None` (never run): `cmp(None, None) = 0` → STALE (producer needs to run)
- If producer has `(0,)` and consumer has `None`: `cmp((0,), None) = 1` → NOT stale (producer already has fresh data)

**Clarification**: `None` represents "hasn't produced data yet" - it compares as LESS THAN any actual generation, which correctly triggers scheduling of unexecuted nodes.

### Hypothesis 2: "Data is stored in a simple dict"
**Status**: CONFIRMED
**Truth**: `_data: dict[DataGeneration, ReturnTupleT_co]` - exactly as hypothesized. The TODO comment confirms this is intentional but may be optimized later.

### Hypothesis 3: "Barriers are for exclusive write access"
**Status**: PARTIALLY CORRECT
**Clarification**: Barriers don't provide "exclusive access" - they provide **read-before-write ordering**. All consumers must read before producer can write next value. No mutex/lock semantics.

### Hypothesis 4: "Stitch level prevents infinite retries"
**Status**: CONFIRMED and CLARIFIED
**Truth**: Stitch level makes producer generations appear older from the perspective of cycle-breaking, ensuring that after using a default, the node waits for actual fresh data rather than immediately reusing the default.

### Hypothesis 5: "Event loop is not asyncio"
**Status**: CONFIRMED
**Truth**: `FlowEventLoop` extends custom `EventLoop` class in `src/flowno/core/event_loop/event_loop.py`. Uses generator-based coroutines with explicit command yielding, not Python's asyncio.

---

## Appendix C: Remaining Unknowns

1. **FlowHDLView finalization exact mechanism**: The `__exit__` method and placeholder resolution code wasn't fully visible in the provided XML. The mechanism is clear from context, but exact implementation details would require examining `flow_hdl_view.py`.

2. **Priority/ordering in resolution queue**: When multiple nodes are ready, the exact scheduling order isn't documented. The `AsyncSetQueue` suggests FIFO but could have different semantics.

3. **Memory management for _data dict**: The TODO suggests this is a known optimization target. Current behavior keeps all generations which could be memory-intensive for long-running flows.

---

## Summary of Key Findings

1. **Generations are hierarchical versions**: `(main_execution, streaming_level_1, streaming_level_2, ...)`. Shorter = more final.

2. **Barriers are producer-consumer synchronization**: Not mutexes. They ensure all consumers read before producer writes next value.

3. **Staleness uses clipped+stitched comparison**: Producer generation is clipped to consumer's run_level, stitched for cycle-breaking, then compared.

4. **Stitch level breaks cycles**: Incremented when using defaults, makes producer appear older on next staleness check.

5. **Status transitions are command-driven**: Nodes yield commands to event loop, which updates status and schedules tasks accordingly.

6. **Streaming inputs are Streams, nonstreaming are values**: `gather_inputs()` wraps streaming connections in `Stream` objects, passes values directly for nonstreaming.
