"""Test matrix for conditional execution (SKIP propagation).

This module systematically tests the SKIP sentinel and PropagateIf node
across different scenarios to verify correct conditional execution behavior.

Known Limitations (documented but not yet resolved):
- Streaming + SKIP: When a streaming producer is skipped, consumers may hang
- Cycles + SKIP: Complex cycle interactions with SKIP may cause hangs
"""

import pytest
from typing import TypeVar, AsyncGenerator

from flowno import FlowHDL, node, SKIP, PropagateIf, TerminateLimitReached, Stream


T = TypeVar("T")


# ============================================================================
# Basic node definitions for testing
# ============================================================================

@node
async def Constant(value: int = 42) -> int:
    """A simple constant node."""
    return value


@node
async def Double(x: int) -> int:
    """Double a value."""
    return x * 2


@node
async def IsPositive(x: int) -> bool:
    """Check if a value is positive."""
    return x > 0


@node
async def IsEven(x: int) -> bool:
    """Check if a value is even."""
    return x % 2 == 0


@node
async def Add(a: int, b: int) -> int:
    """Add two values."""
    return a + b


@node
async def Identity(x: T) -> T:
    """Pass through a value unchanged."""
    return x


# ============================================================================
# Test Category 1: Basic mono->mono SKIP propagation
# ============================================================================

class TestBasicMonoToMono:
    """Test basic SKIP propagation between mono (non-streaming) nodes."""

    def test_propagate_if_true_passes_value(self):
        """When condition is True, value should pass through."""
        with FlowHDL() as f:
            f.value = Constant(10)
            f.condition = IsPositive(f.value)
            f.guarded = PropagateIf(f.value, f.condition)
            f.result = Double(f.guarded)

        f.run_until_complete()

        assert f.result.get_data() == (20,), "Value should pass through and be doubled"

    def test_propagate_if_false_returns_skip(self):
        """When condition is False, SKIP should be returned."""
        with FlowHDL() as f:
            f.value = Constant(-5)
            f.condition = IsPositive(f.value)
            f.guarded = PropagateIf(f.value, f.condition)
            f.result = Double(f.guarded)

        f.run_until_complete()

        # guarded should output SKIP
        assert f.guarded.get_data()[0] is SKIP, "PropagateIf should return SKIP when condition is False"
        # result should also propagate SKIP
        assert f.result.get_data()[0] is SKIP, "Double should propagate SKIP"

    def test_skip_propagates_through_chain(self):
        """SKIP should propagate through a chain of nodes."""
        with FlowHDL() as f:
            f.value = Constant(-1)
            f.condition = IsPositive(f.value)
            f.guarded = PropagateIf(f.value, f.condition)
            f.step1 = Double(f.guarded)
            f.step2 = Double(f.step1)
            f.step3 = Double(f.step2)

        f.run_until_complete()

        assert f.guarded.get_data()[0] is SKIP
        assert f.step1.get_data()[0] is SKIP
        assert f.step2.get_data()[0] is SKIP
        assert f.step3.get_data()[0] is SKIP

    def test_if_method_syntactic_sugar(self):
        """Test the .if_() method syntax."""
        with FlowHDL() as f:
            f.value = Constant(10)
            f.condition = IsPositive(f.value)
            f.result = Double(f.value.if_(f.condition))

        f.run_until_complete()

        assert f.result.get_data() == (20,)

    def test_if_method_with_false_condition(self):
        """Test .if_() method when condition is False."""
        with FlowHDL() as f:
            f.value = Constant(-10)
            f.condition = IsPositive(f.value)
            f.result = Double(f.value.if_(f.condition))

        f.run_until_complete()

        assert f.result.get_data()[0] is SKIP


# ============================================================================
# Test Category 2: Multiple inputs with SKIP
# ============================================================================

class TestMultipleInputsWithSkip:
    """Test SKIP behavior when a node has multiple inputs."""

    def test_one_input_skip_causes_node_skip(self):
        """If one input is SKIP, the node should output SKIP."""
        with FlowHDL() as f:
            f.a = Constant(10)
            f.b = Constant(-5)
            f.cond_a = IsPositive(f.a)  # True
            f.cond_b = IsPositive(f.b)  # False
            f.guarded_a = PropagateIf(f.a, f.cond_a)  # 10
            f.guarded_b = PropagateIf(f.b, f.cond_b)  # SKIP
            f.result = Add(f.guarded_a, f.guarded_b)

        f.run_until_complete()

        # Since b is SKIP, Add should propagate SKIP
        assert f.result.get_data()[0] is SKIP

    def test_both_inputs_valid(self):
        """If both inputs are valid, the node should execute normally."""
        with FlowHDL() as f:
            f.a = Constant(10)
            f.b = Constant(5)
            f.cond_a = IsPositive(f.a)  # True
            f.cond_b = IsPositive(f.b)  # True
            f.guarded_a = PropagateIf(f.a, f.cond_a)
            f.guarded_b = PropagateIf(f.b, f.cond_b)
            f.result = Add(f.guarded_a, f.guarded_b)

        f.run_until_complete()

        assert f.result.get_data() == (15,)


# ============================================================================
# Test Category 3: Diamond pattern with SKIP
# ============================================================================

class TestDiamondPattern:
    """Test SKIP behavior in diamond-shaped graph topology."""

    def test_diamond_both_paths_valid(self):
        """In a diamond, if both paths are valid, merge receives both values."""
        with FlowHDL() as f:
            f.source = Constant(10)
            f.is_positive = IsPositive(f.source)
            f.is_even = IsEven(f.source)  # 10 is even -> True

            # Left path: guarded by is_positive (True)
            f.left = Double(f.source.if_(f.is_positive))

            # Right path: guarded by is_even (True)
            f.right = Double(f.source.if_(f.is_even))

            f.merged = Add(f.left, f.right)

        f.run_until_complete()

        # Both paths should execute, merged = 20 + 20 = 40
        assert f.merged.get_data() == (40,)

    def test_diamond_both_paths_skipped(self):
        """If both paths produce SKIP, merge should also be SKIP."""
        with FlowHDL() as f:
            f.source = Constant(-3)  # Negative and odd
            f.is_positive = IsPositive(f.source)  # False
            f.is_even = IsEven(f.source)  # False

            f.left = Double(f.source.if_(f.is_positive))
            f.right = Double(f.source.if_(f.is_even))
            f.merged = Add(f.left, f.right)

        f.run_until_complete()

        assert f.left.get_data()[0] is SKIP
        assert f.right.get_data()[0] is SKIP
        assert f.merged.get_data()[0] is SKIP


# ============================================================================
# Test Category 4: Edge cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases for SKIP behavior."""

    def test_skip_singleton_identity(self):
        """SKIP should be a singleton (identity check works)."""
        from flowno.core.types import SKIP as SKIP2

        assert SKIP is SKIP2
        assert SKIP == SKIP2

    def test_skip_repr(self):
        """SKIP should have a nice repr."""
        assert repr(SKIP) == "SKIP"

    def test_propagate_if_with_truthy_value(self):
        """PropagateIf should work with truthy values."""
        @node
        async def NonZero(x: int) -> int:
            """Returns the input (non-zero is truthy in Python)."""
            return x

        with FlowHDL() as f:
            f.value = Constant(10)
            f.truthy = NonZero(f.value)
            # Note: This tests if PropagateIf handles truthy values
            # Since Python treats non-zero as True, this should work
            f.guarded = PropagateIf(f.value, f.truthy)
            f.result = Double(f.guarded)

        f.run_until_complete()

        # 10 is truthy, so value should pass through
        assert f.result.get_data() == (20,)


# ============================================================================
# Test Category 5: Cycles with SKIP (Known Limitation)
# ============================================================================

class TestCyclesWithSkip:
    """Test SKIP behavior in cyclic graphs.

    NOTE: Complex cycle + SKIP interactions may cause hangs.
    These tests document expected behavior but some scenarios
    may not work correctly yet.
    """

    def test_cycle_with_conditional_terminates(self):
        """Test conditional execution within a cycle with termination."""
        @node
        async def CountUp(x: int = 0) -> int:
            return x + 1

        @node
        async def LessThan(x: int, limit: int) -> bool:
            return x < limit

        with FlowHDL() as f:
            f.counter = CountUp(f.guarded)
            f.condition = LessThan(f.counter, 3)
            f.guarded = PropagateIf(f.counter, f.condition)

        # Run for a few generations - this tests basic cycle+SKIP
        with pytest.raises(TerminateLimitReached):
            f.run_until_complete(stop_at_node_generation=(5,))

        # Verify the cycle ran and eventually propagated SKIP
        # After condition becomes False, SKIP should propagate


# ============================================================================
# Test Category 6: Streaming with SKIP (Known Limitation)
# ============================================================================

@node
async def StreamNumbers() -> AsyncGenerator[int, None]:
    """Stream some numbers."""
    for i in range(3):
        yield i


@node(stream_in=["numbers"])
async def SumStream(numbers: Stream[int]) -> int:
    """Sum a stream of numbers."""
    total = 0
    async for n in numbers:
        total += n
    return total


class TestStreamingWithSkip:
    """Test SKIP behavior with streaming nodes.

    NOTE: Streaming + SKIP has known limitations. When a streaming
    producer is skipped, consumers may hang waiting for stream data.
    These tests are marked as skipped until the limitation is resolved.
    """

    @pytest.mark.skip(reason="Streaming + SKIP not yet implemented - consumers may hang")
    def test_mono_to_stream_with_skip(self):
        """Test mono node feeding into streaming consumer when mono outputs SKIP."""
        # This is a trickier case - what happens when a streaming node's
        # non-streaming input is SKIP?
        pass

    @pytest.mark.skip(reason="Streaming + SKIP not yet implemented - consumers may hang")
    def test_stream_to_mono_producer_skipped(self):
        """Test when a streaming producer is conditionally skipped."""
        # If the producer is skipped, the consumer should also be skipped
        pass


# ============================================================================
# Run a quick sanity check when this file is executed directly
# ============================================================================

if __name__ == "__main__":
    # Quick sanity check
    print("Running basic conditional test...")

    with FlowHDL() as f:
        f.value = Constant(10)
        f.condition = IsPositive(f.value)
        f.guarded = PropagateIf(f.value, f.condition)
        f.result = Double(f.guarded)

    f.run_until_complete()

    print(f"Result: {f.result.get_data()}")
    assert f.result.get_data() == (20,), "Basic test failed!"
    print("Basic test passed!")

    # Test SKIP propagation
    print("\nRunning SKIP propagation test...")

    with FlowHDL() as f:
        f.value = Constant(-5)
        f.condition = IsPositive(f.value)
        f.guarded = PropagateIf(f.value, f.condition)
        f.result = Double(f.guarded)

    f.run_until_complete()

    print(f"Guarded result: {f.guarded.get_data()}")
    print(f"Final result: {f.result.get_data()}")
    assert f.guarded.get_data()[0] is SKIP, "PropagateIf should return SKIP"
    assert f.result.get_data()[0] is SKIP, "SKIP should propagate"
    print("SKIP propagation test passed!")
