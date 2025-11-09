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
from typing import Any, Callable, ClassVar, cast

from flowno.core.event_loop.commands import Command
from flowno.core.event_loop.types import RawTask
from flowno.core.event_loop.tasks import TaskHandle
from flowno.core.flow.flow import Flow
from flowno.core.flow_hdl_view import FlowHDLView
from flowno.core.node_base import (
    DraftInputPortRef,
    DraftNode,
    FinalizedNode,
    NodeContextFactoryProtocol,
    NodePlaceholder,
    OutputPortRefPlaceholder,
)
from flowno.core.types import Generation
from typing_extensions import Self, TypeVarTuple, Unpack, override

_Ts = TypeVarTuple("_Ts")


logger = logging.getLogger(__name__)


class FlowHDL(FlowHDLView):
    """Context manager for constructing and executing dataflow graphs.

    ``FlowHDL`` extends :class:`FlowHDLView` with the ability to run the
    resulting :class:`~flowno.core.flow.flow.Flow`.  Within the ``with`` block
    users may assign draft nodes to attributes and reference not-yet-defined
    nodes freely.  When the context exits, all placeholders are resolved and the
    underlying :class:`Flow` is finalized.

    Example
    -------
    >>> with FlowHDL() as f:
    ...     f.result = Add(f.a, f.b)
    ...     f.a = Source(1)
    ...     f.b = Source(2)
    >>> f.run_until_complete()

    User defined attribute names should not start with an underscore.

    :canonical: :py:class:`flowno.core.flow_hdl.FlowHDL`
    """

    KEYWORDS: ClassVar[list[str]] = [
        "KEYWORDS",
        "run_until_complete",
        "create_task",
        "register_child_result",
    ]
    """Keywords that should not be treated as nodes in the graph."""

    def __init__(self) -> None:
        def _on_register_finalized_node(node: FinalizedNode) -> None:
            """Callback to handle finalized nodes."""
            self._flow.add_node(node)
        super().__init__(on_register_finalized_node=_on_register_finalized_node)
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
        context_factory: Callable[["FinalizedNode"], Any] | None = None,  
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
            context_factory=context_factory,
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
