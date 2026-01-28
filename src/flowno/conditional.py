"""
Conditional execution primitives for Flowno dataflow graphs.

This module provides nodes and utilities for implementing conditional execution,
allowing nodes to be skipped based on boolean conditions.

Example:
    >>> from flowno import FlowHDL, node
    >>> from flowno.conditional import PropagateIf
    >>>
    >>> @node
    ... async def IsPositive(x: int) -> bool:
    ...     return x > 0
    >>>
    >>> @node
    ... async def Print(x: int) -> int:
    ...     print(f"Value: {x}")
    ...     return x
    >>>
    >>> with FlowHDL() as f:
    ...     f.check = IsPositive(f.value)
    ...     f.guarded = PropagateIf(f.value, f.check)
    ...     f.printer = Print(f.guarded)  # Only executes if value > 0
"""

from typing import TypeVar

from flowno.core.types import SKIP, _SkipType
from flowno.decorators import node

_T = TypeVar("_T")


@node
async def PropagateIf(value: _T, condition: bool) -> _T | _SkipType:
    """Propagate a value only if the condition is True, otherwise return SKIP.

    This node acts as a conditional gate in a dataflow graph. When the condition
    is True, the value passes through unchanged. When False, SKIP is returned,
    which will cause downstream nodes to be skipped as well.

    There is nothing special about this node beyond how SKIP is handled in the
    dataflow execution engine. Any node could technically implement this behavior by
    checking a condition and returning SKIP when not met.

    Args:
        value: The value to propagate if condition is True
        condition: Boolean condition to check

    Returns:
        The input value if condition is True, otherwise SKIP

    Note:
        The argument order is (value, condition) to support the `.if_()` method
        syntax: `node.if_(condition)` creates `PropagateIf(node, condition)`.
    """
    if condition:
        return value
    return SKIP


__all__ = ["PropagateIf", "SKIP"]
