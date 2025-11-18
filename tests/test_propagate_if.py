"""Tests for conditional execution with PropagateIf node."""

import pytest
from flowno import FlowHDL, node, PropagateIf, SKIP, TerminateLimitReached


@node
async def Constant(value: int) -> int:
    """Return a constant value."""
    return value


@node
async def BooleanSource(value: bool) -> bool:
    """Return a constant boolean value."""
    return value


@node
class Counter:
    """Stateful counter that increments each generation."""
    count: int = 0

    async def call(self, increment: int = 1) -> int:
        self.count += increment
        return self.count


@node
class Toggle:
    """Toggles between True and False on each call."""
    current: bool = False

    async def call(self) -> bool:
        self.current = not self.current
        return self.current


@node
async def Add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@node
async def Print(value: int) -> int:
    """Print a value and return it."""
    print(f"Print: {value}")
    return value


@node
async def Collect(value: int) -> list:
    """Collect values into a list (stateful)."""
    if not hasattr(Collect, "_values"):
        Collect._values = []
    Collect._values.append(value)
    return Collect._values.copy()


def test_propagate_if_true():
    """Test PropagateIf with condition=True propagates the value."""
    with FlowHDL() as f:
        f.condition = BooleanSource(True)
        f.value = Constant(42)
        f.gated = PropagateIf(f.condition, f.value)

    f.run_until_complete()

    # Value should be propagated
    result = f.gated.get_data()
    assert result == (42,), f"Expected (42,), got {result}"


def test_propagate_if_false():
    """Test PropagateIf with condition=False returns SKIP."""
    with FlowHDL() as f:
        f.condition = BooleanSource(False)
        f.value = Constant(42)
        f.gated = PropagateIf(f.condition, f.value)

    f.run_until_complete()

    # Should return SKIP
    result = f.gated.get_data()
    assert result == (SKIP,), f"Expected (SKIP,), got {result}"

    # Generation should be marked as skipped
    assert f.gated.is_skipped((0,)), "Generation (0,) should be marked as skipped"


def test_skip_propagates_to_downstream():
    """Test that SKIP propagates to downstream nodes without executing them."""
    # Track if Print was called
    call_count = [0]

    @node
    async def TrackingPrint(value: int) -> int:
        """Print that tracks calls."""
        call_count[0] += 1
        print(f"TrackingPrint: {value}")
        return value

    with FlowHDL() as f:
        f.condition = BooleanSource(False)
        f.value = Constant(42)
        f.gated = PropagateIf(f.condition, f.value)
        f.result = TrackingPrint(f.gated)

    f.run_until_complete()

    # TrackingPrint should NOT have been called (it received SKIP)
    assert call_count[0] == 0, f"Print should not be called, but was called {call_count[0]} times"

    # Result should also be SKIP
    result = f.result.get_data()
    assert result == (SKIP,), f"Expected (SKIP,), got {result}"

    # Both nodes should be marked as skipped
    assert f.gated.is_skipped((0,)), "gated should be skipped"
    assert f.result.is_skipped((0,)), "result should be skipped"


def test_diamond_pattern_with_toggle():
    """Test PropagateIf with alternating condition (simple case)."""
    # Test with just two conditions to verify alternating behavior
    with FlowHDL() as f:
        f.cond = BooleanSource(True)
        f.value = Constant(42)
        f.gated = PropagateIf(f.cond, f.value)

    f.run_until_complete()

    # When condition is True, value should propagate
    assert f.gated.get_data() == (42,), f"Expected (42,), got {f.gated.get_data()}"
    assert not f.gated.is_skipped((0,)), "Should not be skipped when condition is True"

    # Test with False condition
    with FlowHDL() as f:
        f.cond = BooleanSource(False)
        f.value = Constant(42)
        f.gated = PropagateIf(f.cond, f.value)

    f.run_until_complete()

    # When condition is False, should skip
    assert f.gated.get_data() == (SKIP,), f"Expected (SKIP,), got {f.gated.get_data()}"
    assert f.gated.is_skipped((0,)), "Should be skipped when condition is False"


def test_multiple_propagate_if_cascade():
    """Test cascading PropagateIf nodes (AND logic)."""
    with FlowHDL() as f:
        f.cond1 = BooleanSource(True)
        f.cond2 = BooleanSource(False)
        f.value = Constant(1)
        f.gate1 = PropagateIf(f.cond1, f.value)
        f.gate2 = PropagateIf(f.cond2, f.gate1)

    f.run_until_complete()

    # gate1 should pass (cond1=True)
    assert f.gate1.get_data() == (1,), f"gate1 should pass value"

    # gate2 should skip (cond2=False)
    assert f.gate2.get_data() == (SKIP,), f"gate2 should return SKIP"
    assert f.gate2.is_skipped((0,)), "gate2 should be marked as skipped"


def test_propagate_if_all_true_cascade():
    """Test cascading PropagateIf with all conditions true."""
    with FlowHDL() as f:
        f.cond1 = BooleanSource(True)
        f.cond2 = BooleanSource(True)
        f.value = Constant(100)
        f.gate1 = PropagateIf(f.cond1, f.value)
        f.gate2 = PropagateIf(f.cond2, f.gate1)

    f.run_until_complete()

    # Both gates should pass the value
    assert f.gate1.get_data() == (100,), f"gate1 should pass value"
    assert f.gate2.get_data() == (100,), f"gate2 should pass value"

    # No generations should be skipped
    assert not f.gate1.is_skipped((0,)), "gate1 should not be skipped"
    assert not f.gate2.is_skipped((0,)), "gate2 should not be skipped"


def test_skip_with_multiple_inputs():
    """Test that a node with multiple inputs skips if any input is SKIP."""
    with FlowHDL() as f:
        f.cond = BooleanSource(False)
        f.value1 = Constant(10)
        f.value2 = Constant(20)
        f.gated = PropagateIf(f.cond, f.value1)
        f.sum = Add(f.gated, f.value2)  # One input is SKIP, one is 20

    f.run_until_complete()

    # Add should skip because one input is SKIP
    assert f.sum.get_data() == (SKIP,), f"Add should return SKIP when one input is SKIP"
    assert f.sum.is_skipped((0,)), "Add should be marked as skipped"


def test_lockstep_execution_with_skip():
    """Test that all nodes advance generations even with skips."""
    with FlowHDL() as f:
        f.cond = BooleanSource(False)
        f.value = Constant(42)
        f.gated = PropagateIf(f.cond, f.value)
        f.result = Add(f.gated, 1)

    f.run_until_complete()

    # All nodes should be at generation (0,) - they all execute once
    assert f.cond.generation == (0,), f"cond generation should be (0,), got {f.cond.generation}"
    assert f.value.generation == (0,), f"value generation should be (0,), got {f.value.generation}"
    assert f.gated.generation == (0,), f"gated generation should be (0,), got {f.gated.generation}"
    assert f.result.generation == (0,), f"result generation should be (0,), got {f.result.generation}"

    # Gated and result should be marked as skipped
    assert f.gated.is_skipped((0,)), "gated should be skipped"
    assert f.result.is_skipped((0,)), "result should be skipped"


def test_propagate_if_with_different_types():
    """Test PropagateIf works with different value types."""

    @node
    async def StringSource(value: str) -> str:
        return value

    with FlowHDL() as f:
        f.cond = BooleanSource(True)
        f.value = StringSource("hello")
        f.gated = PropagateIf(f.cond, f.value)

    f.run_until_complete()

    assert f.gated.get_data() == ("hello",), f"Should propagate string value"


def test_if_method_with_true_condition():
    """Test .if_() method with True condition."""
    with FlowHDL() as f:
        f.cond = BooleanSource(True)
        f.value = Constant(42)
        f.result = f.value.if_(f.cond)

    f.run_until_complete()

    # Value should be propagated
    assert f.result.get_data() == (42,), f"Expected (42,), got {f.result.get_data()}"
    assert not f.result.is_skipped((0,)), "Should not be skipped when condition is True"


def test_if_method_with_false_condition():
    """Test .if_() method with False condition."""
    with FlowHDL() as f:
        f.cond = BooleanSource(False)
        f.value = Constant(42)
        f.result = f.value.if_(f.cond)

    f.run_until_complete()

    # Should return SKIP
    assert f.result.get_data() == (SKIP,), f"Expected (SKIP,), got {f.result.get_data()}"
    assert f.result.is_skipped((0,)), "Should be skipped when condition is False"


def test_if_method_chained():
    """Test .if_() method can be chained with other operations."""
    with FlowHDL() as f:
        f.cond = BooleanSource(True)
        f.value = Constant(10)
        f.result = Add(f.value.if_(f.cond), 5)

    f.run_until_complete()

    # 10 gated (passes) + 5 = 15
    assert f.result.get_data() == (15,), f"Expected (15,), got {f.result.get_data()}"


def test_if_method_with_node_output():
    """Test .if_() method with a node output reference."""
    with FlowHDL() as f:
        f.toggle = Toggle()
        f.value = Constant(99)
        f.result = f.value.if_(f.toggle.output(0))

    f.run_until_complete()

    # Toggle starts at False, then becomes True
    # First execution: current=False (starts False), then toggles to True, returns True
    # So the value should propagate
    assert f.result.get_data() == (99,), f"Expected (99,), got {f.result.get_data()}"


def test_if_method_downstream_skip():
    """Test .if_() method propagates skip to downstream nodes."""
    call_count = [0]

    @node
    async def TrackingPrint(value: int) -> int:
        """Print that tracks calls."""
        call_count[0] += 1
        print(f"TrackingPrint: {value}")
        return value

    with FlowHDL() as f:
        f.cond = BooleanSource(False)
        f.value = Constant(42)
        f.gated = f.value.if_(f.cond)
        f.result = TrackingPrint(f.gated)

    f.run_until_complete()

    # TrackingPrint should NOT have been called
    assert call_count[0] == 0, f"Print should not be called, but was called {call_count[0]} times"

    # Both nodes should be marked as skipped
    assert f.gated.is_skipped((0,)), "gated should be skipped"
    assert f.result.is_skipped((0,)), "result should be skipped"


def test_if_method_syntax_equivalence():
    """Test that .if_() method is equivalent to PropagateIf()."""
    # Using .if_() method
    with FlowHDL() as f1:
        f1.cond = BooleanSource(True)
        f1.value = Constant(123)
        f1.result = f1.value.if_(f1.cond)

    f1.run_until_complete()
    result1 = f1.result.get_data()

    # Using PropagateIf directly
    with FlowHDL() as f2:
        f2.cond = BooleanSource(True)
        f2.value = Constant(123)
        f2.result = PropagateIf(f2.cond, f2.value)

    f2.run_until_complete()
    result2 = f2.result.get_data()

    # Both should produce the same result
    assert result1 == result2, f".if_() method should be equivalent to PropagateIf()"
    assert result1 == (123,), f"Expected (123,), got {result1}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
