# PropagateIf Implementation - Exploration Summary

This document summarizes the exploratory work done to understand Flowno's execution model in preparation for implementing the `PropagateIf` conditional execution node.

## Key Concepts Discovered

### 1. Generation System

**Location**: `src/flowno/core/types.py:10-11`

```python
DataGeneration: TypeAlias = tuple[int, ...]
Generation: TypeAlias = DataGeneration | None
```

- Generations are tuples of integers: `(0,)`, `(1,)`, `(0, 0)`, `(1, 2)`, etc.
- `None` represents an uninitialized/never-executed node
- Each position in the tuple represents a **run level** (0=final data, 1+=streaming/partial data)
- Example: `(3, 2)` means generation 3 at run level 0, sub-generation 2 at run level 1

**Generation tracking**: `src/flowno/core/node_base.py:520-521`
```python
@property
def generation(self) -> Generation:
    return max(self._data.keys(), key=cmp_to_key(cmp_generation), default=None)
```

The generation is the maximum key in the `_data` dict.

### 2. Run Levels

**Location**: `src/flowno/core/types.py:3`

```python
RunLevel: TypeAlias = Literal[0, 1, 2, 3]
```

- Run level 0: Final/complete data
- Run level 1+: Streaming/partial data (for async generators)
- Input ports can specify a `minimum_run_level` to request streaming data
- Generations are "clipped" to run levels for comparison purposes

### 3. Data Storage

**Location**: `src/flowno/core/node_base.py:407`

```python
_data: dict[DataGeneration, ReturnTupleT_co]
```

Each node stores its output data indexed by generation:
- `node._data[(0,)] = (42,)`  # Data at generation (0,)
- `node._data[(1,)] = (43,)`  # Data at generation (1,)

**Pushing data**: `src/flowno/core/node_base.py:563-572`
```python
def push_data(self, data: ReturnTupleT_co | None, run_level: RunLevel = 0) -> None:
    new_generation = inc_generation(self.generation, run_level)
    self._data[tuple(new_generation)] = data
```

**Getting data**: `src/flowno/core/node_base.py:523-543`
```python
def get_data(self, run_level: RunLevel = 0) -> ReturnTupleT_co | None:
    if self.generation is None:
        return None
    # ... clipping logic ...
    return self._data[self.generation]
```

### 4. The Flow Solver Algorithm

The solver is the heart of Flowno's execution model. It determines which nodes need to execute next.

#### Main Resolution Loop

**Location**: `src/flowno/core/flow/flow.py:776-833`

```python
async def _node_resolve_loop(self, ...):
    # 1. Pick initial nodes from unvisited
    while self.unvisited:
        initial_node = self.unvisited.pop(0)
        await self.resolution_queue.put(initial_node)

        # 2. Process resolution queue
        async for current_node in self.resolution_queue:
            # 3. Find which nodes must execute to unblock current_node
            solution_nodes = self._find_node_solution(current_node)

            # 4. Resume those solution nodes
            for leaf_node in solution_nodes:
                self._mark_node_as_visited(leaf_node)
                await _resume_node(leaf_node)
```

#### The _find_node_solution Algorithm

**Location**: `src/flowno/core/flow/flow.py:835-863`

This is the KEY method for understanding how to implement PropagateIf.

```python
def _find_node_solution(self, node: FinalizedNode) -> list[FinalizedNode]:
    """
    Find the nodes that are ultimately preventing the given node from running.

    Steps:
    1. Build a condensed graph of strongly connected components (SCCs)
    2. Find the leaf SCCs in this condensed graph
    3. For each leaf SCC, pick a node to force evaluate based on default values
    """
    supernode_root = self._condensed_tree(node)

    nodes_to_force_evaluate: list[FinalizedNode] = []
    for supernode in self._find_leaf_supernodes(supernode_root):
        nodes_to_force_evaluate.append(self._pick_node_to_force_evaluate(supernode))

    return nodes_to_force_evaluate
```

#### The Condensed Tree (Tarjan's Algorithm)

**Location**: `src/flowno/core/flow/flow.py:865-1018`

The condensed tree algorithm:

1. **Builds a subgraph of "stale" edges** - edges where input generation ≤ node generation
2. **Uses Tarjan's DFS** to find Strongly Connected Components (SCCs/cycles)
3. **Creates SuperNodes** representing each SCC
4. **Builds dependencies** between SuperNodes

**Critical function**: `get_subgraph_edges()` (line 902-944)
- Returns only "stale" edges (where upstream needs to advance)
- Filters based on node status (Stalled vs normal)
- Skips edges where input has a default value

**Stale detection**: `src/flowno/core/node_base.py:587-634`
```python
def get_inputs_with_le_generation_clipped_to_minimum_run_level(self) -> list[FinalizedInputPort]:
    """
    Returns inputs where:
    - Input node generation is clipped to the input port's minimum run level
    - Clipped generation ≤ this node's generation (stale!)
    """
    stale_inputs: list[FinalizedInputPort[object]] = []
    for input_port in self._input_ports.values():
        input_node = input_port.connected_output.node

        # Clip input generation to minimum run level
        clipped_gen = clip_generation(input_node.generation, input_port.minimum_run_level)

        # Add stitch value
        clipped_gen = stitched_generation(clipped_gen, input_port.stitch_level_0)

        # Compare: if clipped_gen <= self.generation, input is stale
        if cmp_generation(clipped_gen, self.generation) <= 0:
            stale_inputs.append(input_port)

    return stale_inputs
```

#### Finding Leaf Supernodes

**Location**: `src/flowno/core/flow/flow.py:1020-1038`

```python
def _find_leaf_supernodes(self, root: SuperNode) -> list[SuperNode]:
    """
    Identify all leaf supernodes in the condensed DAG.
    Leaf supernodes are those with no dependencies.
    """
    final_leaves: list[SuperNode] = []

    def dfs(current: SuperNode):
        if not current.dependencies:
            final_leaves.append(current)
            return
        for dep in current.dependencies:
            dfs(dep)

    dfs(root)
    return final_leaves
```

**THIS IS WHERE WE COULD CHECK FOR SKIP!**

If a leaf supernode consists of a single skipped node, we should return an empty list instead of trying to pick a node to force evaluate.

#### Picking Node to Force Evaluate

**Location**: `src/flowno/core/flow/flow.py:1040-1059`

```python
def _pick_node_to_force_evaluate(self, leaf_supernode: SuperNode) -> FinalizedNode:
    """
    Pick a node to force evaluate according to the cycle breaking heuristic.
    Picks the first node in the SCC that has defaults for all its cyclic inputs.
    """
    for node, input_ports in leaf_supernode.members.items():
        if all(node.has_default_for_input(input_port) for input_port in input_ports):
            return node
    raise MissingDefaultError(leaf_supernode)
```

### 5. Node Evaluation

**Location**: `src/flowno/core/flow/flow.py:572-623`

```python
async def evaluate_node(self, node: FinalizedNode) -> Never:
    """The persistent task that evaluates a node."""
    while True:
        # 1. Wait to be resumed
        await _wait_for_start_next_generation(node, 0)

        # 2. Gather inputs
        positional_arg_values, defaulted_inputs = node.gather_inputs()

        # 3. Call the node
        returned = node.call(*positional_arg_values)

        # 4. Handle result (coroutine or async generator)
        if isinstance(returned, Coroutine):
            await self._handle_coroutine_node(node, returned)
        else:
            await self._handle_async_generator_node(node, returned)

        # 5. Enqueue downstream nodes
        await self._enqueue_output_nodes(node)
```

**Gathering inputs**: `src/flowno/core/node_base.py:657-725`

This is where nodes read data from their inputs:

```python
def gather_inputs(self) -> GatheredInputs:
    inputs: dict[InputPortIndex, object | Stream] = {}
    defaulted_ports: list[InputPortIndex] = []

    for input_port_index, input_port in self._input_ports.items():
        input_node = input_port.connected_output.node

        # KEY LINE: Get data from upstream node
        last_data = input_node.get_data(run_level=input_port.minimum_run_level)

        if last_data is None:
            # Use default or error
            if self.has_default_for_input(input_port_index):
                individual_last_data = input_port.default_value
                defaulted_ports.append(input_port_index)
            else:
                raise MissingDefaultError(self, input_port_index)
        else:
            # Extract the specific output port data we need
            individual_last_data = last_data[input_port.connected_output.port_index]

        inputs[input_port_index] = individual_last_data

    return self.GatheredInputs(tuple(positional_args), defaulted_ports)
```

**CRITICAL INSIGHT**: Line 708 extracts data from the tuple:
```python
individual_last_data = last_data[input_port.connected_output.port_index]
```

This assumes `last_data` is a tuple. If we return a sentinel, this will fail!

## Where to Check for _SKIP Sentinel

Based on the exploration, here are the potential places to check for `_SKIP`:

### Option 1: In `_find_leaf_supernodes()` or after calling it

**Location**: `src/flowno/core/flow/flow.py:860-861`

```python
for supernode in self._find_leaf_supernodes(supernode_root):
    # CHECK: Is this supernode a single skipped node?
    if is_supernode_skipped(supernode):
        continue  # Don't add to nodes_to_force_evaluate
    nodes_to_force_evaluate.append(self._pick_node_to_force_evaluate(supernode))
```

### Option 2: In `get_subgraph_edges()`

**Location**: `src/flowno/core/flow/flow.py:902-944`

When determining which edges are "stale", check if the upstream node produced `_SKIP`:

```python
def get_subgraph_edges(node: FinalizedNode):
    for port in stale_inputs:
        if self.is_input_defaulted(node, port.port_index):
            continue

        # NEW CHECK: Is the input data _SKIP?
        if port.connected_output is not None:
            upstream_node = port.connected_output.node
            upstream_data = upstream_node.get_data(...)
            if upstream_data is _SKIP:
                continue  # Don't include this edge in the stale subgraph

        yield port
```

### Option 3: In `gather_inputs()`

**Location**: `src/flowno/core/node_base.py:692-708`

```python
last_data = input_node.get_data(run_level=run_level)
if last_data is None:
    # Use default
    ...
elif last_data is _SKIP:  # NEW CHECK
    # Treat as if node should skip
    # But how to propagate this up?
    ...
else:
    individual_last_data = last_data[input_port.connected_output.port_index]
```

**Problem**: This happens during node evaluation, which is too late. The solver has already decided to run this node.

### Option 4: Modify the stale comparison logic

**Location**: `src/flowno/core/node_base.py:631`

```python
if cmp_generation(clipped_gen, self.generation) <= 0:
    # Additional check: is the input data _SKIP?
    if input_node.get_data(...) is _SKIP:
        continue  # Don't mark as stale
    stale_inputs.append(input_port)
```

## Recommended Approach

Based on the exploration, here's the recommended implementation strategy:

### 1. Define the `_SKIP` Sentinel

```python
# In src/flowno/core/types.py or a new sentinels.py file
class _SkipType:
    """Sentinel value indicating a node's execution should be skipped."""
    def __repr__(self):
        return "_SKIP"

_SKIP = _SkipType()
```

### 2. Implement PropagateIf

```python
@node
async def PropagateIf(condition: bool, value: Any) -> Any:
    if condition:
        return value
    else:
        # Import from wherever we define it
        from flowno.core.sentinels import _SKIP
        return _SKIP
```

### 3. Modify `get_subgraph_edges()` to Skip _SKIP Edges

In `src/flowno/core/flow/flow.py:902-944`, add a check:

```python
def get_subgraph_edges(node: FinalizedNode):
    stale_inputs = node.get_inputs_with_le_generation_clipped_to_minimum_run_level()

    match self.node_tasks[node].status:
        case NodeTaskStatus.Stalled(stalling_input):
            single_port = node._input_ports[stalling_input.port_index]
            if single_port in stale_inputs and not self.is_input_defaulted(node, single_port.port_index):
                # NEW: Check if upstream is _SKIP
                if not self.is_input_skipped(single_port):
                    yield single_port
        case _:
            for port in stale_inputs:
                if self.is_input_defaulted(node, port.port_index):
                    continue
                # NEW: Check if upstream is _SKIP
                if self.is_input_skipped(port):
                    continue
                yield port

# New helper method
def is_input_skipped(self, port: FinalizedInputPort) -> bool:
    if port.connected_output is None:
        return False
    upstream_node = port.connected_output.node
    upstream_data = upstream_node.get_data(run_level=port.minimum_run_level)
    return upstream_data is _SKIP
```

### 4. Handle _SKIP in `_find_leaf_supernodes()`

When a leaf supernode has all members skipped, it shouldn't block downstream nodes:

```python
def _find_node_solution(self, node: FinalizedNode) -> list[FinalizedNode]:
    supernode_root = self._condensed_tree(node)

    nodes_to_force_evaluate: list[FinalizedNode] = []
    for supernode in self._find_leaf_supernodes(supernode_root):
        # Check if this supernode consists only of skipped nodes
        if self._is_supernode_skipped(supernode):
            # Don't force evaluation - the skip should propagate
            continue
        nodes_to_force_evaluate.append(self._pick_node_to_force_evaluate(supernode))

    return nodes_to_force_evaluate

def _is_supernode_skipped(self, supernode: SuperNode) -> bool:
    """Check if all nodes in the supernode are skipped."""
    for node in supernode.members.keys():
        data = node.get_data()
        if data is not _SKIP:
            return False
    return True
```

## Open Questions

### Q1: What should `node.get_data()` return for a skipped node?

**Options**:
- A. Return `_SKIP` directly (breaks tuple unpacking)
- B. Return `(_SKIP,)` (a tuple containing the sentinel)
- C. Return `None` (ambiguous with uninitialized)

**Recommendation**: Return `(_SKIP,)` to maintain tuple interface consistency.

### Q2: How does skip interact with multiple outputs?

```python
@node(multiple_outputs=True)
async def MultiOut() -> tuple[int, int]:
    return (1, 2)

# What if this is gated?
# gated = PropagateIf(False, MultiOut())
# Should both outputs be _SKIP? Or the whole tuple?
```

**Recommendation**: PropagateIf returns `(_SKIP,)`, which means the single output is the sentinel.

### Q3: What about generation tracking?

Should a skipped node advance its generation?

**Recommendation**: YES! The node should still record that it "executed" at that generation, just with `_SKIP` data. This maintains lockstep.

### Q4: What about streaming (run levels > 0)?

How does skip interact with async generators and streaming?

**Recommendation**: Start with run_level=0 only, defer streaming support.

## Next Steps

1. Create a `_SKIP` sentinel type
2. Implement basic `PropagateIf` node that returns `(_SKIP,)`
3. Add `is_input_skipped()` helper to Flow
4. Modify `get_subgraph_edges()` to skip `_SKIP` inputs
5. Modify `_find_node_solution()` to handle skipped leaf supernodes
6. Run the test cases from `test_propagate_if.py`
7. Iterate based on failures

## Test Strategy

Start with the simplest test and work up:
1. `test_propagate_if_simple_skip` - single gate, constant False
2. `test_propagate_if_simple_pass` - single gate, constant True
3. `test_propagate_if_with_computation` - verify pre-gate executes, post-gate doesn't
4. `test_propagate_if_alternating` - toggle pattern with cycles
5. `test_propagate_if_multiple_gates` - sequential gates (AND logic)
6. `test_propagate_if_diamond_skip` - diamond pattern
7. More complex patterns

## Key Files to Modify

1. `src/flowno/core/types.py` or new `src/flowno/core/sentinels.py` - Define `_SKIP`
2. `src/flowno/core/flow/flow.py` - Modify solver to handle `_SKIP`
3. Create `src/flowno/nodes/propagate_if.py` - Implement the node
4. `tests/test_propagate_if.py` - Already created with test cases

## References

- Flow solver algorithm: `src/flowno/core/flow/flow.py:835-1059`
- Node evaluation: `src/flowno/core/flow/flow.py:572-623`
- Data storage: `src/flowno/core/node_base.py:407, 520-543, 563-572`
- Input gathering: `src/flowno/core/node_base.py:657-725`
- Stale detection: `src/flowno/core/node_base.py:587-634`
