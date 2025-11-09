"""
Flow execution and graph resolution module for Flowno.

This module contains the Flow class, which is the core execution engine for dataflow graphs.
It manages node scheduling, dependency resolution, cycle breaking, and concurrent execution.

Key components:
    - Flow: The main dataflow graph execution engine
    - FlowEventLoop: A custom event loop for handling Flow-specific commands
    - NodeTaskStatus: State tracking for node execution
"""

from contextvars import ContextVar
import logging
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, Awaitable, Coroutine, Generator
from dataclasses import dataclass
from types import coroutine
from typing import Any, Callable, NamedTuple, TypeAlias, cast

from flowno.core.event_loop.commands import Command, StreamCancelCommand
from flowno.core.event_loop.event_loop import EventLoop
from flowno.core.event_loop.queues import AsyncSetQueue
from flowno.core.event_loop.types import RawTask, TaskHandlePacket
from flowno.core.flow.instrumentation import get_current_flow_instrument
from flowno.core.node_base import (
    DraftInputPortRef,
    DraftNode,
    FinalizedInputPort,
    FinalizedInputPortRef,
    FinalizedNode,
    MissingDefaultError,
    NodeContextFactoryProtocol,
    StalledNodeRequestCommand,
    Stream,
    SuperNode,
    StreamCancelled,
)
from flowno.core.types import Generation, InputPortIndex
from flowno.utilities.helpers import cmp_generation
from flowno.utilities.logging import log_async
from typing_extensions import Never, Unpack, override

logger = logging.getLogger(__name__)

AnyFinalizedNode: TypeAlias = FinalizedNode[Unpack[tuple[Any, ...]], tuple[Any, ...]]
ObjectFinalizedNode: TypeAlias = FinalizedNode[
    Unpack[tuple[object, ...]], tuple[object, ...]
]

_current_flow: "Flow | None" = None

def current_flow() -> "Flow | None":
    """Get the currently executing Flow instance.
    
    Returns:
        The current Flow instance, or None if not in a Flow context.
    """
    global _current_flow

    return _current_flow

def current_node() -> AnyFinalizedNode | None:
    """Get the current node from the FlowEventLoop's task context."""
    from flowno.core.event_loop import current_task

    task = current_task()
    flow = current_flow()
    if flow is None:
        return None

    # TODO: replace the data structure with a more efficient reversible mapping
    for node, task_and_status in flow.node_tasks.items():
        if task_and_status.task is task:
            return node

    return None

# Near the top with other module-level functions
def current_context() -> Any:
    """Get the context for the currently executing node. Calls the context factory provided to run_until_complete().
    
    Returns:
        The NodeContext for the current node.
        
    Raises:
        RuntimeError: If called outside a flow, outside a node, or if no context factory was provided.
    """
    flow = current_flow()
    if flow is None:
        raise RuntimeError("current_context() called outside of a flow")
    
    node = current_node()
    if node is None:
        raise RuntimeError("current_context() called outside of a node")

    if flow._context_factory is None:
        raise RuntimeError("No context factory provided to run_until_complete()")

    return flow._context_factory(node)

@dataclass
class WaitForStartNextGenerationCommand(Command):
    """Command to wait for a node to start its next generation."""

    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    run_level: int = 0


@coroutine
def _wait_for_start_next_generation(
    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
    run_level: int = 0,
) -> Generator[WaitForStartNextGenerationCommand, None, None]:
    """Coroutine that yields a command to wait for a node's next generation."""
    return (yield WaitForStartNextGenerationCommand(node, run_level))


@dataclass
class TerminateWithExceptionCommand(Command):
    """Command to terminate the flow with an exception."""

    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    exception: Exception


@coroutine
def _terminate_with_exception(
    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
    exception: Exception,
) -> Generator[TerminateWithExceptionCommand, None, None]:
    """Coroutine that yields a command to terminate with an exception."""
    return (yield TerminateWithExceptionCommand(node, exception))


@dataclass
class TerminateReachedLimitCommand(Command):
    """Command to terminate the flow because a node reached its generation limit."""

    pass


@coroutine
def _terminate_reached_limit() -> Generator[TerminateReachedLimitCommand, None, None]:
    """Coroutine that yields a command to terminate when a generation limit is reached."""
    return (yield TerminateReachedLimitCommand())


class TerminateLimitReached(Exception):
    """Exception raised when a node reaches its generation limit."""

    pass


class NodeExecutionError(Exception):
    """Exception raised when a node execution fails."""

    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]

    def __init__(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ):
        super().__init__(f"Exception in node {node}")
        self.node = node


@dataclass
class ResumeNodeCommand(Command):
    """Command to resume a node's execution."""

    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]


@coroutine
def _resume_node(
    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
) -> Generator[ResumeNodeCommand, None, None]:
    """Resume the concurrent node task. Does not guarantee that the node will resume if already running."""
    return (yield ResumeNodeCommand(node))


class NodeTaskStatus:
    """
    Represents the possible states of a node's task within the flow execution.

    States:
        - Running: The node is currently executing.
        - Ready: The node is ready to execute but not yet running.
        - Error: The node encountered an error during execution.
        - Stalled: The node is blocked waiting on input data.
    """

    @dataclass(frozen=True)
    class Running:
        """Node is actively executing."""

        pass

    @dataclass(frozen=True)
    class Ready:
        """Node is ready to be executed."""

        pass

    @dataclass(frozen=True)
    class Error:
        """Node encountered an error during execution."""

        pass

    @dataclass(frozen=True)
    class Stalled:
        """Node is stalled waiting for input data."""

        stalling_input: FinalizedInputPortRef[object]

    Type: TypeAlias = Ready | Running | Error | Stalled


class NodeTaskAndStatus(NamedTuple):
    """Container for a node's task and its current status."""

    task: RawTask[Command, object, Never]
    status: NodeTaskStatus.Type


class Flow:
    """
    Dataflow graph execution engine.

    The Flow class manages the execution of a dataflow graph, handling dependency
    resolution, node scheduling, and cycle breaking. It uses a custom event loop
    to execute nodes concurrently while respecting data dependencies.

    Key features:
        - Automatic dependency-based scheduling
        - Cycle detection and resolution
        - Support for streaming data (run levels)
        - Concurrency management

    Attributes:
        unvisited: List of nodes that have not yet been visited during execution
        visited: Set of nodes that have been visited
        node_tasks: Dictionary mapping nodes to their tasks and status
        running_nodes: Set of nodes currently running
        resolution_queue: Queue of nodes waiting to be resolved
    """

    # Classvar as instance init
    counter: int = 0

    # Instance attribute types
    unvisited: list[FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]]
    visited: set[FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]]
    _stop_at_node_generation: (
        dict[FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], Generation]
        | Generation
    )

    node_tasks: dict[
        FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], NodeTaskAndStatus
    ]
    running_nodes: set[FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]]
    resolution_queue: AsyncSetQueue[
        FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ]
    _defaulted_inputs: defaultdict[
        FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        list[InputPortIndex],
    ]
    _cancelled_streams: defaultdict[
        FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], set[Stream]
    ]
    _context_factory: Callable[["FinalizedNode"], Any] | None

    resumable: bool
    event_loop: "FlowEventLoop"

    def __init__(self, is_finalized: bool = True):
        """
        Initialize a new Flow instance.

        Args:
            is_finalized: Whether the nodes in this flow are already finalized.
        """
        self.resumable = False
        self.event_loop = FlowEventLoop(self)

        self.counter = Flow.counter
        Flow.counter += 1

        self.unvisited = []
        self.visited = set()
        self._stop_at_node_generation = None
        self.node_tasks = {}
        self.running_nodes = set()
        self.resolution_queue = AsyncSetQueue()
        self._defaulted_inputs = defaultdict(list)
        self._cancelled_streams = defaultdict(set)
        self._context_factory = None

    def set_node_status(
        self,
        node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        status: NodeTaskStatus.Type,
    ) -> None:
        """
        Update the status of a node and notify instrumentation.

        Args:
            node: The node whose status is being updated
            status: The new status to set
        """
        old_status = self.node_tasks[node].status
        get_current_flow_instrument().on_node_status_change(
            self, node, old_status, status
        )
        self.node_tasks[node] = self.node_tasks[node]._replace(status=status)

        if isinstance(status, NodeTaskStatus.Running):
            self.running_nodes.add(node)
        elif node in self.running_nodes:
            self.running_nodes.remove(node)

    def set_defaulted_inputs(
        self,
        node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        defaulted_inputs: list[InputPortIndex],
    ) -> None:
        """
        Mark specific inputs of a node as using default values.

        When a node uses default values for inputs that are part of a cycle,
        this method records that information and increments the stitch level
        to prevent infinite recursion.

        Args:
            node: The node with defaulted inputs
            defaulted_inputs: List of input port indices using default values
        """
        self._defaulted_inputs[node] = defaulted_inputs
        for input_port_index in defaulted_inputs:
            node._input_ports[input_port_index].stitch_level_0 += 1
        get_current_flow_instrument().on_defaulted_inputs_set(
            self, node, defaulted_inputs
        )

    def clear_defaulted_inputs(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ) -> None:
        """
        Remove defaulted input information for a node.

        Args:
            node: The node to clear defaulted inputs for
        """
        _ = self._defaulted_inputs.pop(node, None)

    def is_input_defaulted(
        self,
        node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        input_port: InputPortIndex,
    ) -> bool:
        """
        Check if a specific input port is using a default value.

        Args:
            node: The node to check
            input_port: The input port index to check

        Returns:
            True if the input port is using a default value, False otherwise
        """
        return input_port in self._defaulted_inputs[node]

    async def _terminate_if_reached_limit(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ):
        """
        Check if a node has reached its generation limit and terminate if so.

        Args:
            node: The node to check

        Raises:
            TerminateLimitReached: If the node reached its generation limit
        """
        if isinstance(self._stop_at_node_generation, dict):
            stop_generation = self._stop_at_node_generation.get(node, ())
        else:
            stop_generation = self._stop_at_node_generation

        if cmp_generation(node.generation, stop_generation) >= 0:
            get_current_flow_instrument().on_node_generation_limit(
                self, node, stop_generation
            )
            await _terminate_reached_limit()

    async def _handle_coroutine_node(
        self,
        node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        returned: Awaitable[tuple[object, ...]],
    ):
        """
        Handle a node that returns a coroutine (single output).

        This awaits the result of the node's coroutine and stores the
        result in the node's data.

        Args:
            node: The node to handle
            returned: The coroutine returned by the node's call
        """
        # this is already part of run_level 0 lifecyce instrumentation context
        # in evaluate_node
        result = await returned

        # Wait for the last output data to have been read before overwriting
        with get_current_flow_instrument().on_barrier_node_write(self, node, result, 0):
            await node._barrier0.wait()
        node.push_data(result, 0)
        # Remember how many times output data must be read
        node._barrier0.set_count(len(node.get_output_nodes_by_run_level(0)))

        get_current_flow_instrument().on_node_emitted_data(self, node, result, 0)

    async def _handle_async_generator_node(
        self,
        node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        returned: AsyncGenerator[tuple[object, ...], None],
    ):
        """
        Handle a node that returns an async generator (streaming output).

        This processes each yielded item from the generator, storing them
        as run level 1 data, and accumulates them for the final run level 0
        result when the generator completes.

        Args:
"""
        """
        Handle a node that returns an async generator (streaming output).

        This processes each yielded item from the generator, storing them
        as run level 1 data, and accumulates them for the final run level 0
        result when the generator completes.

        Args:
            node: The node to handle
            returned: The async generator returned by the node's call
        """
        acc: tuple[object, ...] | None = None

        try:
            while True:
                cancelled_streams = self._cancelled_streams.get(node, set())
                logger.debug(f"_node_gen_lifecycle loop start for {node}, cancelled_streams={cancelled_streams}")
                if cancelled_streams:
                    logger.info(f"Cancelling streams for {node}: {cancelled_streams}", extra={"tag": "flow"})
                    # Make a copy before clearing so the local variable remains truthy
                    cancelled_streams = cancelled_streams.copy()
                    self._cancelled_streams[node].clear()

                    # this node has a set of output streams that have been cancelled
                    # currently, there can only be one output stream, but I'm trying
                    # to think ahead to multiple output streams.

                # already part of run_level 0 lifecycle
                    
                with get_current_flow_instrument().node_lifecycle(
                    self, node, run_level=1
                ):
                    if cancelled_streams:
                        # inform the async generator of the cancelled stream
                        # (assumes one output stream for now)
                        try:
                            result = await returned.athrow(
                                StreamCancelled(stream=next(iter(cancelled_streams)))
                            )
                            # If the generator yields after a stream cancellation,
                            # that just means the node wants to disregard the consumer's
                            # cancellation request and continue producing data.
                        except StopAsyncIteration as e:
                            raise
                    else:
                        result = await anext(returned)

                if acc is None:
                    acc = result
                else:
                    try:
                        acc = tuple(
                            node._draft_node.accumulate_streamed_data(acc, result)
                        )
                    except NotImplementedError:
                        acc = None

                # wait for the last output data to have been read before overwriting.
                with get_current_flow_instrument().on_barrier_node_write(
                    self, node, result, 1
                ):
                    await node._barrier1.wait()
                node.push_data(result, 1)
                # remember how many times output data must be read
                node._barrier1.set_count(len(node.get_output_nodes_by_run_level(1)))

                get_current_flow_instrument().on_node_emitted_data(
                    self, node, result, 1
                )

                await self._terminate_if_reached_limit(node)
                await self._enqueue_output_nodes(node)

                await _wait_for_start_next_generation(node, 1)

        except (StreamCancelled, StopAsyncIteration) as e:
            # Stream completed (either cancelled or naturally finished)
            # If StopAsyncIteration has args, use that as the final value (from explicit raise)
            # Otherwise use the accumulated run level 0 value
            
            if isinstance(e, StopAsyncIteration) and e.args:
                # User explicitly passed a final value via raise StopAsyncIteration(value)
                # The wrapper should have already wrapped it in a tuple
                data = e.args[0] if isinstance(e.args[0], tuple) else (e.args[0],)
            elif acc is None:
                data = None
            else:
                data = acc

            # Wait for the last output data to have been read before overwriting
            with get_current_flow_instrument().on_barrier_node_write(self, node, data, 0):
                await node._barrier0.wait()
            node.push_data(data, 0)
            # Remember how many times output data must be read
            node._barrier0.set_count(len(node.get_output_nodes_by_run_level(0)))

            get_current_flow_instrument().on_node_emitted_data(self, node, data, 0)

        except Exception as e:
            # python reraises any exception raised in the async generator as RuntimeError
            # `Exception.__cause__` is the original exception
            if isinstance(e.__cause__, StopAsyncIteration):
                # completion with explicit `raise StopAsyncIteration("final value")`
                if not isinstance(e.__cause__.args[0], tuple):
                    raise ValueError(
                        (
                            "The final value of a node async generator must ",
                            f"be a tuple. Got: {e.__cause__.args[0]}. If ",
                            "you use the @node.tuple decorator you are ",
                            "responsible for wrapping the final value in ",
                            "a tuple.",
                        )
                    )
                data: tuple[object, ...] = e.__cause__.args[0]

                # Wait for the last output data to have been read before overwriting
                with get_current_flow_instrument().on_barrier_node_write(self, node, data, 0):
                    await node._barrier0.wait()
                node.push_data(data, 0)
                # Remember how many times output data must be read
                node._barrier0.set_count(len(node.get_output_nodes_by_run_level(0)))

                get_current_flow_instrument().on_node_emitted_data(self, node, data, 0)
            else:
                raise

    @log_async
    async def evaluate_node(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ) -> Never:
        """
        The persistent task that evaluates a node.

        This is the main execution function for a node. It:
            1. Waits for the node to be ready to run
            2. Gathers inputs and handles defaulted values
            3. Calls the node with its inputs
            4. Processes the result (either coroutine or async generator)
            5. Propagates outputs to dependent nodes
            6. Repeats

        Args:
            node: The node to evaluate

        Returns:
            Never returns; runs as a persistent coroutine

        Raises:
            NotImplementedError: If the node does not return a coroutine or async generator
        """
        while True:
            await _wait_for_start_next_generation(node, 0)
            with get_current_flow_instrument().node_lifecycle(self, node, run_level=0):
                positional_arg_values, defaulted_inputs = node.gather_inputs()

                await node.count_down_upstream_latches(defaulted_inputs)

                try:
                    self.set_defaulted_inputs(node, defaulted_inputs)
                    returned = node.call(*positional_arg_values)

                    # make sure the user used async def.
                    if not isinstance(returned, (Coroutine, AsyncGenerator)):
                        raise NotImplementedError(
                            "Node must be a coroutine (async def) or an AsyncGenerator (async def with yield)"
                        )

                    if isinstance(returned, Coroutine):
                        await self._handle_coroutine_node(node, returned)
                    else:
                        await self._handle_async_generator_node(node, returned)
                except Exception as e:
                    get_current_flow_instrument().on_node_error(self, node, e)
                    # if self.node_unhandled_exception_terminates:
                    await _terminate_with_exception(node, e)
                finally:
                    self.clear_defaulted_inputs(node)
                    await self._terminate_if_reached_limit(node)
                    await self._enqueue_output_nodes(node)

    def add_node(self, node: FinalizedNode[Unpack[tuple[Any, ...]], tuple[Any, ...]]):
        """
        Add a node to the flow.

        Args:
            node: The node to add
        """
        if node in self.unvisited:
            return

        get_current_flow_instrument().on_node_registered(self, node)
        self.unvisited.append(node)
        self._register_node(node)

    def _register_node(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ):
        """
        Register a node's task with the flow.

        This creates the persistent task for the node and adds it to the node_tasks dictionary.

        Args:
            node: The node to register
        """
        task: RawTask[Command, object, Never] = self.evaluate_node(node)
        # prime the coroutine. I choose to structure the evaluate_node while loop this way so
        # it needs to be primed once to get rid of the unawaited coroutine warning
        _ = task.send(None)
        self.node_tasks[node] = NodeTaskAndStatus(task, NodeTaskStatus.Ready())

    def _mark_node_as_visited(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ):
        """
        Mark a node as visited during the resolution process.

        Args:
            node: The node to mark as visited
        """
        get_current_flow_instrument().on_node_visited(self, node)

        if node in self.unvisited:
            # this proves that the node is connected to the graph
            self.unvisited.remove(node)
            self.visited.add(node)
        elif node not in self.visited:
            # current node has not been registered by .add_node()
            self.visited.add(node)
            self._register_node(node)

    def add_nodes(
        self, nodes: list[FinalizedNode[Unpack[tuple[Any, ...]], tuple[Any, ...]]]
    ):
        """
        Add multiple nodes to the flow.

        Args:
            nodes: The nodes to add
        """
        for node in nodes:
            self.add_node(node)

    async def _enqueue_output_nodes(
        self, out_node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ):
        """
        Enqueue all nodes that depend on the given node.

        Args:
            out_node: The node whose dependents should be enqueued
        """
        output_nodes = out_node.get_output_nodes()

        if not self.resolution_queue.closed:
            for out_node in output_nodes:
                get_current_flow_instrument().on_resolution_queue_put(self, out_node)

            await self.resolution_queue.putAll(output_nodes)

    async def _enqueue_node(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ):
        """
        Enqueue a single node for resolution.

        Args:
            node: The node to enqueue
        """
        get_current_flow_instrument().on_resolution_queue_put(self, node)
        await self.resolution_queue.put(node)

    def run_until_complete(
        self,
        stop_at_node_generation: (
            dict[
                FinalizedNode[Unpack[tuple[Any, ...]], tuple[Any, ...]]
                | DraftNode[Unpack[tuple[Any, ...]], tuple[Any, ...]],
                Generation,
            ]
            | Generation
        ) = (),
        terminate_on_node_error: bool = False,
        _debug_max_wait_time: float | None = None,
        context_factory: Callable[["FinalizedNode"], Any] | None = None,
    ):
        """
        Execute the flow until completion or until a termination condition is met.

        This is the main entry point for running a flow. It starts the resolution
        process and runs until all nodes have completed or a termination condition
        (like reaching a generation limit or an error) is met.

        Args:
            stop_at_node_generation: Generation limit for nodes, either as a global
                limit or as a dict mapping nodes to their individual limits
            terminate_on_node_error: Whether to terminate the flow if a node raises an exception
            _debug_max_wait_time: Maximum time in seconds to wait for I/O operations
                (useful for debugging)

        Raises:
            Exception: Any exception raised by nodes and not caught
            TerminateLimitReached: When a node reaches its generation limit
        """
        global _current_flow
        _current_flow = self

        if context_factory:
            self._context_factory = context_factory
        else:
            self._context_factory = None

        self.event_loop.run_until_complete(
            self._node_resolve_loop(
                cast(
                    dict[
                        FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
                        Generation,
                    ]
                    | Generation,
                    stop_at_node_generation,
                ),
                terminate_on_node_error,
            ),
            join=True,
            _debug_max_wait_time=_debug_max_wait_time,
        )

        _current_flow = None

    @log_async
    async def _node_resolve_loop(
        self,
        stop_at_node_generation: (
            dict[
                FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
                Generation,
            ]
            | Generation
        ),
        terminate_on_node_error: bool,
    ):
        """
        Main resolution loop for the flow.

        This function implements the core algorithm for resolving node dependencies
        and executing nodes in the correct order. It:

        1. Picks an initial node
        2. For each node in the resolution queue:
            a. Finds the set of nodes that must be executed first
            b. Marks those nodes as visited
            c. Resumes their execution
        3. Continues until the resolution queue is empty

        Args:
            stop_at_node_generation: Generation limit for nodes
            terminate_on_node_error: Whether to terminate on node errors
        """
        get_current_flow_instrument().on_flow_start(self)
        self._stop_at_node_generation = stop_at_node_generation

        if not self.unvisited:
            logger.warning("No nodes to run.")

        while self.unvisited:
            initial_node = self.unvisited.pop(0)
            if self.resolution_queue.closed:
                self.resolution_queue = AsyncSetQueue()
            get_current_flow_instrument().on_resolution_queue_put(self, initial_node)
            await self.resolution_queue.put(initial_node)

            # blocks until a node is available or the queue is closed
            async for current_node in self.resolution_queue:
                get_current_flow_instrument().on_resolution_queue_get(
                    self, current_node
                )

                solution_nodes = self._find_node_solution(current_node)
                get_current_flow_instrument().on_solving_nodes(
                    self, current_node, solution_nodes
                )

                for leaf_node in solution_nodes:
                    self._mark_node_as_visited(leaf_node)
                    await _resume_node(leaf_node)

        # self.event_loop.clean_up()
        get_current_flow_instrument().on_flow_end(self)

    def _find_node_solution(
        self, node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ) -> list[FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]]:
        """
        Find the nodes that are ultimately preventing the given node from running.

        This method is key to Flowno's cycle resolution algorithm. It:
            1. Builds a condensed graph of strongly connected components (SCCs)
            2. Finds the leaf SCCs in this condensed graph
            3. For each leaf SCC, picks a node to force evaluate based on default values

        Args:
            node: The node whose dependencies need to be resolved

        Returns:
            A list of nodes that should be forced to evaluate to unblock the given node

        Raises:
            MissingDefaultError: If a cycle is detected with no default values to break it
        """
        supernode_root = self._condensed_tree(node)

        nodes_to_force_evaluate: list[
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
        ] = []
        for supernode in self._find_leaf_supernodes(supernode_root):
            nodes_to_force_evaluate.append(self._pick_node_to_force_evaluate(supernode))

        return nodes_to_force_evaluate

    def _condensed_tree(
        self, head: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    ) -> SuperNode:
        """
        Build a condensed graph of strongly connected components (SCCs) from stale connections.

        This method implements Tarjan's algorithm to find strongly connected components
        (cycles) in the dependency graph, but only following connections that are "stale"
        (where the input's generation is <= the node's generation).

        Args:
            head: The starting point for building the condensed graph

        Returns:
            A SuperNode representing the root of the condensed graph
        """
        visited: set[FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]] = (
            set()
        )
        current_scc_stack: list[
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
        ] = []
        on_stack: set[FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]] = (
            set()
        )
        id_counter = 0
        ids: dict[
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], int
        ] = {}
        low_links: dict[
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], int
        ] = {}
        all_sccs: list[SuperNode] = []
        scc_for_node: dict[
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], SuperNode
        ] = {}

        def get_subgraph_edges(
            node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ) -> Generator[FinalizedInputPort[object], None, None]:
            """
            Return the inputs (edges) from `node` to its upstream dependencies that
            belong in the stale subgraph.

            1) Gather all inputs that are stale according to
               get_inputs_with_le_generation_clipped_to_minimum_run_level().

            2) If the node is stalled, we only yield the single stalled input
               (if and only if it is also stale and not defaulted).

            3) Otherwise, we yield all stale, non-defaulted inputs.
            """
            # 1) Collect all stale inputs
            stale_inputs = (
                node.get_inputs_with_le_generation_clipped_to_minimum_run_level()
            )

            # 2) Check node's status
            match self.node_tasks[node].status:
                case NodeTaskStatus.Stalled(stalling_input):
                    # logger.debug(f"{node} is stalled on input port {stalling_input.port_index}")
                    assert stalling_input.node == node

                    # Grab exactly that one input port:
                    single_port = node._input_ports[stalling_input.port_index]

                    # Only yield it if:
                    #   - it's in the stale set
                    #   - it's not defaulted
                    if single_port in stale_inputs and not self.is_input_defaulted(
                        node, single_port.port_index
                    ):
                        yield single_port

                case _:
                    # 3) Normal case: yield all stale, non-defaulted inputs
                    for port in stale_inputs:
                        if self.is_input_defaulted(node, port.port_index):
                            continue
                        yield port

        def tarjan_dfs(
            v: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ):
            """
            Tarjan's algorithm for finding strongly connected components.

            This is a depth-first search that identifies strongly connected
            components (cycles) in the graph.

            Args:
                v: The current node being processed
            """
            nonlocal id_counter

            ids[v] = low_links[v] = id_counter
            id_counter += 1
            current_scc_stack.append(v)
            on_stack.add(v)
            visited.add(v)

            for v_input_ports in get_subgraph_edges(v):
                if v_input_ports.connected_output is None:
                    continue
                dependency: FinalizedNode[
                    Unpack[tuple[object, ...]], tuple[object, ...]
                ] = v_input_ports.connected_output.node
                if dependency not in visited:
                    tarjan_dfs(dependency)
                    low_links[v] = min(low_links[v], low_links[dependency])
                elif dependency in on_stack:
                    low_links[v] = min(low_links[v], ids[dependency])

            if low_links[v] == ids[v]:
                scc_nodes: set[
                    FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
                ] = set()
                while True:
                    w = current_scc_stack.pop()
                    on_stack.remove(w)
                    scc_nodes.add(w)
                    if w == v:
                        break

                members_dict = {
                    node: [
                        port.port_index
                        for port in get_subgraph_edges(node)
                        if port.connected_output
                        and port.connected_output.node in scc_nodes
                    ]
                    for node in scc_nodes
                }
                super_node = SuperNode(head=v, members=members_dict, dependencies=[])
                for member in scc_nodes:
                    scc_for_node[member] = super_node
                all_sccs.append(super_node)

        tarjan_dfs(head)

        # build the condensed graph
        for super_node in all_sccs:
            for member in super_node.members:
                for port in get_subgraph_edges(member):
                    if not port.connected_output:
                        continue
                    dependency: FinalizedNode[
                        Unpack[tuple[object, ...]], tuple[object, ...]
                    ] = port.connected_output.node
                    if scc_for_node[dependency] != super_node:
                        super_node.dependencies.append(scc_for_node[dependency])
                        scc_for_node[dependency].dependent = super_node

        return scc_for_node[head]

    def _find_leaf_supernodes(self, root: SuperNode) -> list[SuperNode]:
        """
        Identify all leaf supernodes in the condensed DAG.
        Leaf supernodes are those with no dependencies.

        Returns:
            list[SuperNode]: A list of all leaf supernodes in the graph.
        """
        final_leaves: list[SuperNode] = []

        def dfs(current: SuperNode):
            if not current.dependencies:
                final_leaves.append(current)
                return
            for dep in current.dependencies:
                dfs(dep)

        dfs(root)
        return final_leaves

    def _pick_node_to_force_evaluate(
        self, leaf_supernode: SuperNode
    ) -> "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]":
        """Pick a node to force evaluate according to the cycle breaking heuristic.

        Args:
            leaf_supernode (SuperNode): The leaf Super-Node of the Condensed subgraph.

        Returns:
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]: The node to force evaluate.

        Undefined Behavior:
            If the argument is not a leaf in the condensed graph, the behavior is undefined.
        """
        for node, input_ports in leaf_supernode.members.items():
            if all(
                node.has_default_for_input(input_port) for input_port in input_ports
            ):
                return node
        raise MissingDefaultError(leaf_supernode)

    @override
    def __repr__(self):
        return f"<Flow#{self.counter}>"


class FlowEventLoop(EventLoop):
    def __init__(self, flow: Flow):
        super().__init__()
        self.flow = flow

    @override
    def _handle_command(
        self,
        current_task_packet: TaskHandlePacket[Command, Any, Any, Exception],
        command: Command,
    ) -> bool:
        if super()._handle_command(current_task_packet, command):
            return True

        if isinstance(command, WaitForStartNextGenerationCommand):
            node = command.node
            self.flow.set_node_status(node, NodeTaskStatus.Ready())
            if not self.flow.running_nodes and not self.flow.resolution_queue:
                # close the resolution queue, allowing the main loop to exit
                # we can't await the .close() method because we are outside a coroutine
                self.handle_queue_close(queue=self.flow.resolution_queue)

        elif isinstance(command, TerminateWithExceptionCommand):
            node = command.node
            self.flow.set_node_status(node, NodeTaskStatus.Error())
            if not self.flow.running_nodes and not self.flow.resolution_queue:
                # close the resolution queue, allowing the main loop to exit
                # we can't await the .close() method because we are outside a coroutine
                self.handle_queue_close(queue=self.flow.resolution_queue)
            raise command.exception

        elif isinstance(command, TerminateReachedLimitCommand):
            raise TerminateLimitReached()

        elif isinstance(command, ResumeNodeCommand):
            node = command.node
            current_task = current_task_packet[0]

            if node not in self.flow.running_nodes:
                self.flow.set_node_status(node, NodeTaskStatus.Running())

                # queue up the node's task to run before the current task
                self.tasks.append((self.flow.node_tasks[node][0], None, None))
                # continue the current task afterwards (always flow._node_resolve_loop() task)
                self.tasks.append((current_task, None, None))
            else:
                # node is already running, it has a task in the queue
                # just schedule the current task again
                self.tasks.append((current_task, None, None))

        elif isinstance(command, StalledNodeRequestCommand):
            stalled_input = command.stalled_input
            stalling_node = command.stalling_node
            self.flow.set_node_status(
                stalled_input.node, NodeTaskStatus.Stalled(stalled_input)
            )
            get_current_flow_instrument().on_node_stalled(
                self.flow, stalling_node, stalled_input
            )
            self.tasks.insert(0, (self.flow._enqueue_node(stalling_node), None, None))

        elif isinstance(command, StreamCancelCommand):
            # _node = command.node
            producer_node = command.producer_node
            stream = command.stream
            current_task = current_task_packet[0]

            self.flow._cancelled_streams[producer_node].add(stream)

            # # Resume the producer node so it can check for cancelled streams
            # # The producer might be suspended waiting for the next generation
            # if producer_node in self.flow.node_tasks:
            #     producer_task = self.flow.node_tasks[producer_node][0]
            #     # Remove the producer task if it's already in the queue to avoid duplicates
            #     filtered_tasks = deque(
            #         (t, ex, tb) for (t, ex, tb) in self.tasks if t != producer_task
            #     )
            #     self.tasks = filtered_tasks
            #     # Insert producer task to run next
            #     self.tasks.insert(0, (producer_task, None, None))

            # Immediately resume the current task. The order probably doesn't matter here, but
            # I'm worried about nodes in the resolution queue being executed in a surprising order.
            self.tasks.insert(0, (current_task, None, None))

        else:
            return False
        return True
