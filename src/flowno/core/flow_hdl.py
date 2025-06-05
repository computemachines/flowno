"""
FlowHDL: Hardware Description Language-inspired context for defining dataflow graphs.

This module provides the FlowHDL context manager which allows users to:
- Define nodes and their connections in any order
- Forward reference nodes before they are created (for cyclic dependencies)
- Automatically finalize node connections when exiting the context

Example:
    >>> from flowno import FlowHDL, node
    >>>
    >>> @node
    ... async def Add(x, y):
    ...     return x + y
    ...
    >>> @node
    ... async def Source(value):
    ...     return value
    ...
    >>> with FlowHDL() as f:
    ...     f.output = Add(f.input1, f.input2)  # Reference nodes before definition
    ...     f.input1 = Source(1)                # Define nodes in any order
    ...     f.input2 = Source(2)
    ...
    >>> f.run_until_complete()
    >>> f.output.get_data()
    (3,)
"""

import inspect
import logging
from types import TracebackType
from typing import Any, ClassVar, cast

from flowno.core.event_loop.commands import Command
from flowno.core.event_loop.types import RawTask
from flowno.core.event_loop.tasks import TaskHandle
from flowno.core.flow.flow import Flow
from flowno.core.flow_hdl_view import FlowHDLView
from flowno.core.node_base import (
    DraftInputPortRef,
    DraftNode,
    FinalizedNode,
    NodePlaceholder,
    OutputPortRefPlaceholder,
)
from flowno.core.types import Generation
from typing_extensions import Self, TypeVarTuple, Unpack, override

_Ts = TypeVarTuple("_Ts")


logger = logging.getLogger(__name__)


class FlowHDL(FlowHDLView):
    """Context manager for building dataflow graphs.

    The FlowHDL context allows:

    - Assigning nodes as attributes
    - Forward-referencing nodes that haven't been defined yet
    - Automatic resolution of placeholder references when exiting the context

    Attributes within the context become nodes in the final flow. The context
    automatically finalizes all node connections when exited.

    Use the special syntax:

    >>> with FlowHDL() as f:
    ...     f.node1 = Node1(f.node2)
    ...     f.node2 = Node2()
    >>> f.run_until_complete()

    User defined attributes should not start with an underscore.

    :canonical: :py:class:`flowno.core.flow_hdl.FlowHDL`
    """

    KEYWORDS: ClassVar[list[str]] = ["KEYWORDS", "run_until_complete", "create_task"]
    """Keywords that should not be treated as nodes in the graph."""

    def __init__(self) -> None:
        self._flow: Flow = Flow(is_finalized=False)
    
    @override
    def __getattribute__(self, key):
        return super().__getattribute__(key)

    @override
    def __getattr__(self, key):
        return super().__getattr__(key)
    

    def run_until_complete(
        self,
        stop_at_node_generation: (
            dict[
                DraftNode[Unpack[tuple[Any, ...]], tuple[Any, ...]]
                | FinalizedNode[Unpack[tuple[Any, ...]], tuple[Any, ...]],
                Generation,
            ]
            | Generation
        ) = (),
        terminate_on_node_error: bool = True,
        _debug_max_wait_time: float | None = None,
    ) -> None:
        """Run the flow until all nodes have completed processing.

        Args:
            stop_at_node_generation: Optional generation number or mapping of nodes to generation
                                    numbers to stop execution at
            terminate_on_node_error: Whether to terminate the entire flow if any node raises an exception
            _debug_max_wait_time: Maximum time to wait for nodes to complete (for debugging only)
        """
        self._flow.run_until_complete(
            stop_at_node_generation=stop_at_node_generation,
            terminate_on_node_error=terminate_on_node_error,
            _debug_max_wait_time=_debug_max_wait_time,
        )


    def create_task(
        self,
        raw_task: RawTask[Command, Any, Any],
    ) -> "TaskHandle[Command]":
        """
        Create a new task handle for the given raw task and enqueue
        the task in the event loop's task queue.
        
        Args:
            raw_task: The raw task to create a handle for.
        
        Returns:
            A TaskHandle object representing the created task.
        """
        return self._flow.event_loop.create_task(raw_task)
