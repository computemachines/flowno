"""
Instrumentation system for Flowno's dataflow execution.

This module provides tools for monitoring and debugging dataflow graph execution, 
including node evaluation, data propagation, and cycle resolution. It uses a context
manager pattern similar to the event loop instrumentation, allowing different monitoring
tools to be applied to specific flows.

Example:
    >>> from flowno import node, FlowHDL
    >>> from flowno.core.flow.instrumentation import MinimalInstrument
    >>> 
    >>> # Define a simple flow with two nodes
    >>> @node
    ... async def NumberNode(value: int = 5):
    ...     return value
    >>> 
    >>> @node
    ... async def DoubleNode(value: int):
    ...     return value * 2
    >>> 
    >>> # Create a simple instrumentation class
    >>> class MinimalInstrument(FlowInstrument):
    ...     def on_flow_start(self, flow):
    ...         print(f"Flow started: {flow}")
    ...     
    ...     def on_flow_end(self, flow):
    ...         print(f"Flow completed: {flow}")
    ...     
    ...     @contextmanager
    ...     def node_lifecycle(self, flow, node, run_level):
    ...         print(f"Starting node: {node} (run_level: {run_level})")
    ...         try:
    ...             yield
    ...         finally:
    ...             print(f"Completed node: {node} (run_level: {run_level})")
    >>> 
    >>> # Run the flow with instrumentation
    >>> with FlowHDL() as f:
    ...     f.number = NumberNode()
    ...     f.double = DoubleNode(f.number)
    >>> 
    >>> with MinimalInstrument():
    ...     f.run_until_complete()
    Flow started: <flowno.core.flow.flow.Flow object at 0x...>
    Starting node: NumberNode#... (run_level: 0)
    Completed node: NumberNode#... (run_level: 0)
    Starting node: DoubleNode#... (run_level: 0)
    Completed node: DoubleNode#... (run_level: 0)
    Flow completed: <flowno.core.flow.flow.Flow object at 0x...>
    >>> 
    >>> print(f.double.get_data())
    (10,)
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, TypeAlias

from typing_extensions import Unpack, override

if TYPE_CHECKING:
    from flowno.core.flow.flow import Flow
    from flowno.core.node_base import FinalizedInputPortRef, FinalizedNode, Stream
    from flowno.core.types import Generation
    from flowno.core.flow.flow import NodeTaskStatus
    from flowno.core.types import InputPortIndex

import logging

logger = logging.getLogger(__name__)

_current_flow_instrument: ContextVar[FlowInstrument | None] = ContextVar("_current_flow_instrument", default=None)

ObjectNode: TypeAlias = "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"


class FlowInstrument:
    """
    Base class for Flowno dataflow instrumentation.
    
    This class provides hooks for various flow events, allowing monitoring of node
    execution, data propagation, and dependency resolution. Subclasses can override
    specific methods to track different aspects of flow execution.
    
    Key events:
    - Flow start/end
    - Node registration and state changes
    - Data emission and propagation
    - Dependency resolution steps
    - Node execution lifecycle
    """

    def __init__(self) -> None:
        """Initialize the instrument."""
        self._token: Token[FlowInstrument | None] | None = None

    def __enter__(self) -> FlowInstrument:
        """
        Start using this instrument for flow execution.
        
        Returns:
            self: The instrument instance for context manager usage
        """
        self._token = _current_flow_instrument.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """
        Stop using this instrument and restore the previous one.
        
        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
            
        Returns:
            bool: False to propagate exceptions, True to suppress
        """
        assert self._token
        _current_flow_instrument.reset(self._token)
        return False

    def on_flow_start(self, flow: Flow) -> None:
        """
        Called just before the Flow starts running (e.g. in run_until_complete).
        
        Args:
            flow: The flow that is starting execution
        """
        pass

    def on_flow_end(self, flow: Flow) -> None:
        """
        Called immediately after the Flow finishes run_until_complete.
        
        Args:
            flow: The flow that has completed execution
        """
        pass

    def on_node_registered(self, flow: Flow, node: ObjectNode) -> None:
        """
        Called when a node is first added/registered to the flow.
        
        Args:
            flow: The flow the node is being registered with
            node: The node being registered
        """
        pass

    def on_node_visited(self, flow: Flow, node: ObjectNode) -> None:
        """
        Called whenever the flow "marks" a node as visited in the resolution queue.
        
        Args:
            flow: The flow executing the node
            node: The node being marked as visited
        """
        pass

    def on_resolution_queue_put(self, flow: Flow, node: ObjectNode) -> None:
        """
        Called when a node is pushed onto the resolution queue.
        
        Args:
            flow: The flow managing the resolution queue
            node: The node being queued for resolution
        """
        pass

    def on_resolution_queue_get(self, flow: Flow, node: ObjectNode) -> None:
        """
        Called when a node is popped from the resolution queue.
        
        Args:
            flow: The flow managing the resolution queue
            node: The node being processed from the queue
        """
        pass

    def on_solving_nodes(self, flow: Flow, head_node: ObjectNode, solution_nodes: list[ObjectNode]) -> None:
        """
        Called when the flow forcibly evaluates a set of leaf dependencies.
        
        This happens after `_find_solution_nodes(head_node)` returns.
        
        Args:
            flow: The flow solving the dependencies
            head_node: The node whose dependencies are being solved
            solution_nodes: The set of nodes that will be evaluated to unblock head_node
        """
        pass

    def on_node_resumed(self, flow: Flow, node: ObjectNode, run_level: int) -> None:
        """
        Called when a node is resumed at a given run level.
        
        Args:
            flow: The flow resuming the node
            node: The node being resumed
            run_level: The run level at which the node is resuming (0=regular, 1=streaming)
        """
        pass

    def on_node_stalled(self, flow: Flow, node: ObjectNode, stalled_input: FinalizedInputPortRef[Any]) -> None:
        """
        Called when a node transitions to 'Stalled' status because of a blocked input port.
        
        Args:
            flow: The flow containing the stalled node
            node: The node that has stalled
            stalled_input: Reference to the input port causing the stall
        """
        pass

    def on_node_emitted_data(self, flow: Flow, node: ObjectNode, data: tuple[Any, ...] | None, run_level: int) -> None:
        """
        Called when a node yields or returns data at a particular run level.
        
        Args:
            flow: The flow the node is part of
            node: The node emitting data
            data: The data being emitted (tuple or None)
            run_level: The run level of the data (0=regular, 1=streaming)
        """
        pass

    def on_node_generation_limit(self, flow: Flow, node: ObjectNode, limit: Generation) -> None:
        """
        Called if the node hits a user-specified generation limit.
        
        Args:
            flow: The flow the node is part of
            node: The node hitting its limit
            limit: The generation limit that was reached
        """
        pass

    def on_node_error(self, flow: Flow, node: ObjectNode, error: Exception) -> None:
        """
        Called when a node raises an exception.
        
        Args:
            flow: The flow the node is part of
            node: The node raising the exception
            error: The exception that was raised
        """
        pass

    def on_node_pause(self, flow: Flow, node: ObjectNode, run_level: int) -> None:
        """
        Called when a node is paused.
        
        Args:
            flow: The flow the node is part of
            node: The node being paused
            run_level: The run level at which the node is paused
        """
        pass

    def on_node_status_change(
        self, flow: Flow, node: ObjectNode, old_status: NodeTaskStatus.Type, new_status: NodeTaskStatus.Type
    ) -> None:
        """
        Called when the node changes status.
        
        Args:
            flow: The flow the node is part of
            node: The node changing status
            old_status: The previous status of the node
            new_status: The new status of the node
        """
        pass

    def on_stream_start(self, stream: Stream[Any]) -> None:
        """
        Called when a Stream starts processing.
        
        Args:
            stream: The stream that is starting
        """
        pass

    def on_stream_next(self, stream: Stream[Any], data: Any) -> None:
        """
        Called each time a Stream processes the next item.
        
        Args:
            stream: The stream processing data
            data: The data item being processed
        """
        pass

    def on_stream_end(self, stream: Stream[Any]) -> None:
        """
        Called when a Stream has no more items to process.
        
        Args:
            stream: The stream that has completed
        """
        pass

    def on_stream_error(self, stream: Stream[Any], error: Exception) -> None:
        """
        Called when a Stream encounters an error.
        
        Args:
            stream: The stream encountering an error
            error: The exception that was raised
        """
        pass

    @contextmanager
    def on_barrier_node_write(self, flow: Flow, node: ObjectNode, data: tuple[Any, ...], run_level: int):
        """
        Context manager for tracking node write barrier events.
        
        A write barrier ensures all downstream nodes have consumed previous data
        before new data is written, preventing data loss.
        
        Args:
            flow: The flow containing the node
            node: The node writing data
            data: The data being written
            run_level: The run level of the operation
        """
        # Before write
        try:
            yield
        finally:
            # After write
            pass

    @contextmanager
    def on_barrier_node_read(self, node: ObjectNode, run_level: int):
        """
        Context manager for tracking node read barrier events.
        
        A read barrier notifies upstream nodes that their data has been consumed,
        allowing them to proceed with generating new data.
        
        Args:
            node: The node reading data
            run_level: The run level of the operation
        """
        # Before read
        try:
            yield
        finally:
            # After read
            pass

    @contextmanager
    def node_lifecycle(self, flow: Flow, node: ObjectNode, run_level: int):
        """
        Context manager for tracking the complete lifecycle of a node evaluation.
        
        This wraps the entire process of a node gathering its inputs, computing
        results, and producing outputs.
        
        Args:
            flow: The flow containing the node
            node: The node being evaluated
            run_level: The run level of the evaluation
        """
        # Before node evaluation
        try:
            yield
        finally:
            # After node evaluation
            pass

    def on_defaulted_inputs_set(self, flow: Flow, node: ObjectNode, defaulted_inputs: list[InputPortIndex]) -> None:
        """
        Called when defaulted inputs for a node are set and the stitch levels are incremented.
        
        This is important for cycle resolution, as defaulted inputs break cycles in the flow.
        
        Args:
            flow: The flow containing the node
            node: The node with defaulted inputs
            defaulted_inputs: List of input port indices using default values
        """
        pass


class PrintInstrument(FlowInstrument):
    """
    A concrete implementation of FlowInstrument that prints flow and node execution events.
    
    This instrument is useful for debugging and understanding the execution order
    of nodes in a flow.
    """

    print = print  # Makes it easy to subclass and redirect output

    @override
    def on_flow_start(self, flow):
        self.print(f"[FLOW-START] Flow {flow} has started.")

    @override
    def on_flow_end(self, flow):
        self.print(f"[FLOW-END] Flow {flow} has completed.")

    @override
    def on_node_registered(self, flow, node):
        self.print(f"[NODE-REGISTERED] Node {node} was registered in the flow.")

    @override
    def on_node_visited(self, flow, node):
        self.print(f"[NODE-VISITED] Node {node} was visited during execution.")

    @override
    def on_resolution_queue_put(self, flow, node):
        self.print(f"[QUEUE-PUT] Node {node} was added to the resolution queue.")

    @override
    def on_resolution_queue_get(self, flow, node):
        self.print(f"[QUEUE-GET] Node {node} was retrieved from the resolution queue.")

    @override
    def on_solving_nodes(self, flow, head_node, solution_nodes):
        self.print(f"[SOLVED-NODES] Resolution solution to {head_node}: {solution_nodes}")

    @override
    def on_node_resumed(self, flow, node, run_level):
        self.print(f"[NODE-RESUMED] Node {node} resumed execution at run level {run_level}.")

    @override
    def on_node_stalled(self, flow, node, stalled_input):
        self.print(f"[NODE-STALLED] Input {stalled_input} stalled due to stale node: {node}")

    @override
    def on_node_emitted_data(self, flow, node, data, run_level):
        self.print(f"[NODE-OUTPUT] Node {node} emitted data {data} at run level {run_level}.")

    @override
    def on_node_generation_limit(self, flow, node, limit):
        self.print(f"[NODE-LIMIT] Node {node} reached its generation limit {limit}.")

    @override
    def on_node_error(self, flow, node, error: Exception):
        self.print(f"[NODE-ERROR] Node {node} encountered an error: {error}")

    @override
    def on_node_pause(self, flow, node, run_level):
        self.print(f"[NODE-PAUSED] Node {node} paused execution after generating data for run level {run_level}")

    @override
    def on_node_status_change(
        self, flow: Flow, node: ObjectNode, old_status: NodeTaskStatus.Type, new_status: NodeTaskStatus.Type
    ) -> None:
        self.print(f"[NODE-STATUS-CHANGE] Node {node} changed status from {old_status} to {new_status}.")

    @override
    def on_stream_start(self, stream):
        self.print(f"[STREAM-START] Stream {stream} has started processing.")

    @override
    def on_stream_next(self, stream, data):
        self.print(f"[STREAM-NEXT] Stream {stream} processed next item: {data!r}")

    @override
    def on_stream_end(self, stream):
        self.print(f"[STREAM-END] Stream {stream} has completed processing.")

    @override
    def on_stream_error(self, stream, error: Exception):
        self.print(f"[STREAM-ERROR] Stream {stream} encountered an error: {error}")

    @override
    @contextmanager
    def on_barrier_node_write(self, flow: Flow, node: ObjectNode, data: tuple[Any, ...], run_level: int):
        self.print(
            f"[WRITE-BARRIER-START] Node {node} will block until downstream nodes have consumed last data. (run level: {run_level})"
        )
        try:
            yield
        finally:
            self.print(f"[WRITE-BARRIER-END] Node {node} is unblocked. Writing data: {data}. (run level: {run_level})")

    @override
    @contextmanager
    def on_barrier_node_read(self, node: ObjectNode, run_level: int):
        self.print(
            f"[READ-BARRIER-START] Informing Node {node} that available data is being read. (run level: {run_level})"
        )
        try:
            yield
        finally:
            self.print(f"[READ-BARRIER-END] Done")

    @contextmanager
    def node_lifecycle(self, flow: Flow, node, run_level: int):
        self.print(f"[NODE-EVAL-START] Evaluating node {node} at run level {run_level}")
        try:
            yield
        finally:
            self.print(f"[NODE-EVAL-END] Finished evaluating node {node} at run level {run_level}")

    @override
    def on_defaulted_inputs_set(self, flow: Flow, node: ObjectNode, defaulted_inputs: list[InputPortIndex]) -> None:
        self.print(f"[DEFAULTED-INPUTS] Node {node} defaulted inputs: {defaulted_inputs}.")


class LogInstrument(PrintInstrument):
    """
    A version of PrintInstrument that sends output to the logger instead of stdout.
    
    This instrument uses debug level logging for all messages.
    """
    print = logger.debug


class MinimalInstrument(FlowInstrument):
    """
    A simplified instrument that only tracks flow start/end and node lifecycle.
    
    This is useful for basic monitoring without excessive output.
    """
    
    def on_flow_start(self, flow):
        print(f"Flow started: {flow}")
    
    def on_flow_end(self, flow):
        print(f"Flow completed: {flow}")
    
    @contextmanager
    def node_lifecycle(self, flow, node, run_level):
        print(f"Starting node: {node} (run_level: {run_level})")
        try:
            yield
        finally:
            print(f"Completed node: {node} (run_level: {run_level})")


NO_OP_INSTRUMENT: Final[FlowInstrument] = FlowInstrument()


def get_current_flow_instrument() -> FlowInstrument:
    """
    Get the current flow instrumentation context.
    
    Returns:
        The currently active flow instrument or a no-op instrument if none is active
    """
    inst = _current_flow_instrument.get()
    if inst is None:
        return NO_OP_INSTRUMENT
    return inst


__all__ = [
    "FlowInstrument",
    "PrintInstrument",
    "LogInstrument",
    "MinimalInstrument",
    "get_current_flow_instrument",
    "NO_OP_INSTRUMENT",
]
