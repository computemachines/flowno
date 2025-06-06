"""
Tests for edge cases involving anonymous nodes in Flowno dataflow graphs.

This module tests various scenarios with anonymous nodes to ensure proper handling
of node finalization, connections, and data flow.
"""

from flowno import FlowHDL, node, Stream, TerminateLimitReached
from typing import TypeVar, Any, cast
from pytest import raises

T = TypeVar("T")


# Basic nodes for testing
@node
async def Identity(x: T) -> T:
    return x


@node
async def Add(x: int, y: int = 0) -> int:
    return x + y


@node
async def MultiplyByTwo(x: int) -> int:
    return x * 2


@node(stream_in=["values"])
async def StreamSum(values: Stream[int]) -> int:
    total = 0
    async for value in values:
        total += value
    return total


@node
async def NumberSource(limit: int = 5):
    for i in range(limit):
        yield i


def test_orphaned_anonymous_node():
    """Test anonymous node that isn't connected to any named nodes."""
    with FlowHDL() as f:
        # Create an anonymous Add node not connected to anything
        Add(1, 2)
        # Named node that we'll actually use
        f.result = Identity(42)

    f.run_until_complete()
    assert f.result.get_data() == (42,)


def test_mixed_anonymous_named_cycle():
    """Test cycles involving both anonymous and named nodes."""
    with FlowHDL() as f:
        # Create a cycle with mix of anonymous and named nodes
        f.start = Identity(MultiplyByTwo(Add(1, f.start)))

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.start: (2,)})

    assert f.start.get_data() == (14,)


def test_anonymous_multiple_outputs():
    """Test anonymous node outputs being used by multiple consumers."""
    with FlowHDL() as f:
        source = Add(5, 3)  # Anonymous node
        f.result1 = Identity(source)
        f.result2 = MultiplyByTwo(source)  # Reuse output

    f.run_until_complete()
    assert f.result1.get_data() == (8,)
    assert f.result2.get_data() == (16,)


def test_anonymous_streaming():
    """Test anonymous streaming nodes."""
    with FlowHDL() as f:
        # Anonymous streaming source connected to named consumer
        f.sum = StreamSum(NumberSource())

    f.run_until_complete()
    assert f.sum.get_data() == (10,)  # Sum of 0,1,2,3,4


def test_deep_anonymous_chain():
    """Test chain of anonymous nodes."""
    with FlowHDL() as f:
        # Create deep chain: Identity(MultiplyByTwo(Add(Identity(5), 3)))
        f.result = Identity(MultiplyByTwo(Add(Identity(5), 3)))

    f.run_until_complete()
    assert f.result.get_data() == (16,)


def test_anonymous_multiple_paths():
    """Test anonymous node discovered through multiple paths."""
    with FlowHDL() as f:
        source = Add(2, 3)  # Anonymous source
        intermediate1 = MultiplyByTwo(source)  # Path 1
        intermediate2 = Add(source, 1)  # Path 2
        f.result1 = Identity(intermediate1)
        f.result2 = Identity(intermediate2)

    f.run_until_complete()
    assert f.result1.get_data() == (10,)  # (2+3)*2
    assert f.result2.get_data() == (6,)  # (2+3)+1


def test_anonymous_default_values():
    """Test anonymous nodes with default values."""

    @node
    async def WithDefault(x: int = 42) -> int:
        return x

    with FlowHDL() as f:
        f.result = Identity(WithDefault())  # Anonymous node with default value

    f.run_until_complete()
    assert f.result.get_data() == (42,)


def test_anonymous_error_propagation():
    """Test error propagation through anonymous nodes."""

    @node
    async def RaiseError() -> Any:
        raise ValueError("Test error")

    with FlowHDL() as f:
        f.result = Identity(RaiseError())

    with raises(ValueError) as exc_info:
        f.run_until_complete()
    assert str(exc_info.value) == "Test error"
