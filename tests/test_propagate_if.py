"""
Test cases for PropagateIf conditional execution node.

These tests define the expected behavior of conditional execution in Flowno.
The PropagateIf node should:
1. Return its value input when condition is True
2. Return _SKIP sentinel when condition is False
3. Cause downstream nodes to skip when _SKIP is propagated
4. Maintain generation lockstep (all non-skipped nodes at same generation)
"""

import pytest
from flowno import FlowHDL, node
from flowno.core.types import Generation


# Simple helper nodes for testing
@node
async def Constant(value: int) -> int:
    """Returns a constant value."""
    return value


@node
async def BooleanSource(value: bool) -> bool:
    """Returns a constant boolean."""
    return value


@node
async def Add(a: int, b: int) -> int:
    """Adds two integers."""
    return a + b


@node
async def Counter(self: int = 0) -> int:
    """Counts up from 0."""
    return self + 1


@node
async def Toggle(self: bool = True) -> bool:
    """Alternates between True and False."""
    return not self


@node
async def Collect(value: int) -> int:
    """Just passes through value, used to observe data."""
    print(f"Collected: {value}")
    return value


# This is what we want to implement
# @node
# async def PropagateIf(condition: bool, value: Any) -> Any:
#     """
#     Conditionally propagates a value.
#     - If condition is True: returns value
#     - If condition is False: returns _SKIP sentinel
#     """
#     if condition:
#         return value
#     else:
#         # TODO: Return _SKIP sentinel
#         # This should signal to the solver that downstream nodes should skip
#         pass


# ============================================================================
# Test 1: Simple skip with constant False condition
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_simple_skip():
    """
    When condition is False, downstream nodes should skip execution.
    The Collect node should not receive any data.
    """
    collected_values = []

    @node
    async def CollectToList(value: int) -> int:
        collected_values.append(value)
        return value

    with FlowHDL() as f:
        f.value = Constant(42)
        f.condition = BooleanSource(False)
        # f.gated = PropagateIf(f.condition, f.value)
        # f.result = CollectToList(f.gated)

    f.run_until_complete()

    # The CollectToList node should never execute, so list should be empty
    assert collected_values == []


# ============================================================================
# Test 2: Simple pass-through with constant True condition
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_simple_pass():
    """
    When condition is True, value should propagate normally.
    """
    collected_values = []

    @node
    async def CollectToList(value: int) -> int:
        collected_values.append(value)
        return value

    with FlowHDL() as f:
        f.value = Constant(42)
        f.condition = BooleanSource(True)
        # f.gated = PropagateIf(f.condition, f.value)
        # f.result = CollectToList(f.gated)

    f.run_until_complete()

    # The CollectToList node should execute once with value 42
    assert collected_values == [42]


# ============================================================================
# Test 3: Diamond pattern - skip should propagate through multiple paths
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_diamond_skip():
    """
    When a node in a diamond is skipped, all downstream should skip.

    Flow structure:
         source
           |
        path_a (Add 10)
           |
         gated (PropagateIf False)
          / \\
      left   right (both Add operations)
         \\  /
         merge (Add)
    """
    collected_values = []

    @node
    async def CollectToList(value: int) -> int:
        collected_values.append(value)
        return value

    with FlowHDL() as f:
        f.source = Constant(10)
        f.path_a = Add(f.source, 10)  # = 20
        # f.gated = PropagateIf(False, f.path_a)  # Skip!
        # f.left = Add(f.gated, 5)
        # f.right = Add(f.gated, 15)
        # f.merge = Add(f.left, f.right)
        # f.result = CollectToList(f.merge)

    f.run_until_complete()

    # Everything downstream of the gate should skip
    assert collected_values == []


# ============================================================================
# Test 4: Alternating skip pattern with Toggle
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_alternating():
    """
    Using a Toggle node, every other generation should skip.
    This tests that skip state is generation-specific.
    """
    collected_values = []

    @node
    async def CollectToList(value: int) -> int:
        collected_values.append(value)
        return value

    with FlowHDL() as f:
        f.toggle = Toggle(f.toggle)  # True, False, True, False, ...
        f.counter = Counter(f.counter)  # 1, 2, 3, 4, ...
        # f.gated = PropagateIf(f.toggle, f.counter)
        # f.result = CollectToList(f.gated)

    from flowno.core.flow.flow import TerminateLimitReached

    with pytest.raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(5,))

    # Should collect values only when toggle was True
    # Generation 0: toggle=True (default), counter=1 -> collect 1
    # Generation 1: toggle=False, counter=2 -> skip
    # Generation 2: toggle=True, counter=3 -> collect 3
    # Generation 3: toggle=False, counter=4 -> skip
    # Generation 4: toggle=True, counter=5 -> collect 5
    assert collected_values == [1, 3, 5]


# ============================================================================
# Test 5: Multiple sequential gates (AND logic)
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_multiple_gates():
    """
    Two gates in sequence: both must be True for data to pass.
    Tests that _SKIP propagates through multiple PropagateIf nodes.
    """
    collected_values = []

    @node
    async def CollectToList(value: int) -> int:
        collected_values.append(value)
        return value

    # Test all combinations: TT, TF, FT, FF
    test_cases = [
        (True, True, [42]),    # Both true: pass
        (True, False, []),      # First true, second false: skip
        (False, True, []),      # First false: skip (second doesn't matter)
        (False, False, []),     # Both false: skip
    ]

    for cond1, cond2, expected in test_cases:
        collected_values.clear()

        with FlowHDL() as f:
            f.value = Constant(42)
            f.condition1 = BooleanSource(cond1)
            f.condition2 = BooleanSource(cond2)
            # f.gate1 = PropagateIf(f.condition1, f.value)
            # f.gate2 = PropagateIf(f.condition2, f.gate1)
            # f.result = CollectToList(f.gate2)

        f.run_until_complete()

        assert collected_values == expected, f"Failed for cond1={cond1}, cond2={cond2}"


# ============================================================================
# Test 6: Skip with computation before gate
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_with_computation():
    """
    Nodes before the gate should execute normally.
    Only nodes after the gate should skip.
    """
    pre_gate_executions = []
    post_gate_executions = []

    @node
    async def TrackPreGate(value: int) -> int:
        pre_gate_executions.append(value)
        return value + 10

    @node
    async def TrackPostGate(value: int) -> int:
        post_gate_executions.append(value)
        return value

    with FlowHDL() as f:
        f.source = Constant(42)
        f.computed = TrackPreGate(f.source)  # Should execute: 42 + 10 = 52
        # f.gated = PropagateIf(False, f.computed)  # Skip here
        # f.result = TrackPostGate(f.gated)  # Should NOT execute

    f.run_until_complete()

    # Pre-gate should execute
    assert pre_gate_executions == [42]
    # Post-gate should not execute
    assert post_gate_executions == []


# ============================================================================
# Test 7: Generation tracking - skipped nodes should advance generation
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_generation_tracking():
    """
    Even when skipped, nodes should track that they "executed" at that generation.
    This maintains the lockstep invariant.
    """
    with FlowHDL() as f:
        f.counter = Counter(f.counter)
        # f.gated = PropagateIf(False, f.counter)

    from flowno.core.flow.flow import TerminateLimitReached

    with pytest.raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(3,))

    # Counter should be at generation (3,)
    assert f.counter.generation == (3,)

    # Gated node should also be at generation (3,) even though it skipped
    # assert f.gated.generation == (3,)

    # Counter should have data at generation (3,)
    assert f.counter.get_data() == (4,)  # Started at 0, incremented 4 times

    # Gated node should NOT have data (it was skipped)
    # But it should have recorded that it skipped at generations (0,), (1,), (2,), (3,)
    # assert f.gated.get_data() is ??? # What should this be?


# ============================================================================
# Test 8: Exploring what get_data() should return for skipped nodes
# ============================================================================
@pytest.mark.skip(reason="PropagateIf not yet implemented")
def test_propagate_if_skip_data_semantics():
    """
    Question: What should a skipped node's get_data() return?

    Options:
    A. None (like uninitialized)
    B. _SKIP sentinel
    C. Previous non-skipped value
    D. Something else?

    This test explores the semantics.
    """
    with FlowHDL() as f:
        f.toggle = Toggle(f.toggle)  # True, False, True, False
        f.counter = Counter(f.counter)  # 1, 2, 3, 4
        # f.gated = PropagateIf(f.toggle, f.counter)

    from flowno.core.flow.flow import TerminateLimitReached

    with pytest.raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(4,))

    # At generation (0,): toggle=True, counter=1 -> gated should have data
    # What is gated.get_data(0)?

    # At generation (1,): toggle=False, counter=2 -> gated skipped
    # What is gated.get_data(1)?

    # This test is meant to explore and document the expected behavior
    pass


# ============================================================================
# Additional test ideas (not implemented yet)
# ============================================================================

# Test 9: Parallel gates (two independent PropagateIf nodes)
# - Two separate condition chains that don't interact
# - Tests that skip state doesn't leak between independent branches

# Test 10: Cycle with PropagateIf
# - What happens if PropagateIf is in a cycle?
# - Does the cycle breaking algorithm work with skip state?

# Test 11: Streaming with PropagateIf
# - What happens with run levels and streaming?
# - Should skip affect sub-generations?

# Test 12: Error handling
# - What if condition node errors?
# - What if value node errors before the gate?
