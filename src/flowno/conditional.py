"""Conditional execution nodes for Flowno.

This module provides nodes that implement conditional data flow:
    - PropagateIf: Conditionally propagates data based on a boolean condition
    - PropagateStreamIf: Conditionally propagates streaming data based on a boolean condition
"""

from collections.abc import AsyncGenerator
from typing import Any, TypeVar

from flowno.core.node_base import Stream
from flowno.core.types import SKIP
from flowno.decorators.node import node

_T = TypeVar("_T")


@node
async def PropagateIf(condition: bool, value: _T) -> _T:
    """Conditionally propagate data through the dataflow graph.

    When condition is True, the value is propagated to downstream nodes.
    When condition is False, this node returns SKIP, causing downstream
    nodes to also skip execution at this generation.

    This maintains the lockstep execution invariant: all nodes still
    advance their generation counters, but skipped nodes don't execute
    their computation.

    Args:
        condition: Boolean value determining whether to propagate
        value: The data to propagate when condition is True

    Returns:
        The value when condition is True, SKIP when condition is False

    Example:
        >>> with FlowHDL() as f:
        ...     f.enabled = BooleanSource(True)
        ...     f.data = IntSource(42)
        ...     f.gated = PropagateIf(f.enabled, f.data)
        ...     f.result = Print(f.gated)  # Only prints when enabled
    """
    if condition:
        return value
    else:
        return SKIP


@node(stream_in=["value"])
async def PropagateStreamIf(condition: bool, value: Stream[_T]) -> AsyncGenerator[_T, _T]:
    """Conditionally propagate streaming data through the dataflow graph.

    When condition is True, all stream values are propagated to downstream nodes.
    When condition is False, this node yields SKIP for each stream item and returns
    SKIP as the final value, causing downstream nodes to skip execution.

    The condition is evaluated once (monovalue), but applies to the entire stream.

    Args:
        condition: Boolean value determining whether to propagate the stream
        value: The streaming data to propagate when condition is True

    Yields:
        Stream items when condition is True, SKIP for each item when condition is False

    Returns:
        Final stream value when condition is True, SKIP when condition is False

    Example:
        >>> @node
        ... async def StreamNumbers() -> AsyncGenerator[int, None]:
        ...     for i in range(5):
        ...         yield i
        ...     raise StopAsyncIteration(sum(range(5)))
        ...
        >>> with FlowHDL() as f:
        ...     f.enabled = BooleanSource(True)
        ...     f.stream = StreamNumbers()
        ...     f.gated = PropagateStreamIf(f.enabled, f.stream)
    """
    if condition:
        # Propagate all stream values
        async for item in value:
            yield item
        # The final value is returned via StopAsyncIteration from the stream
    else:
        # Consume the stream but yield SKIP for each item
        async for item in value:
            yield SKIP
        # Return SKIP as the final value via StopAsyncIteration
        raise StopAsyncIteration(SKIP)


__all__ = ["PropagateIf", "PropagateStreamIf"]
