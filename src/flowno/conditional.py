"""Conditional execution nodes for Flowno.

This module provides nodes that implement conditional data flow:
    - PropagateIf: Conditionally propagates data based on a boolean condition
"""

from typing import Any, TypeVar

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


__all__ = ["PropagateIf"]
