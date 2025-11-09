"""
Core node types and base classes for the Flowno dataflow system.

This module defines the fundamental building blocks of the dataflow graph:
    - DraftNode: Base class for all nodes before finalization
    - FinalizedNode: Runtime node with active connections
    - Stream: For handling streaming data between nodes
    - Various port and connection types for graph construction

These classes are primarily internal implementation details.
"""

import inspect
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator, Coroutine, Generator
from dataclasses import dataclass, field
from functools import cmp_to_key
from types import CodeType, coroutine
from typing import (
    Any,
    ClassVar,
    Generic,
    NamedTuple,
    TypeAlias,
    TypeVar,
    cast,
    final,
    overload,
)

from flowno.core.event_loop.commands import Command, StreamCancelCommand
from flowno.core.event_loop.synchronization import CountdownLatch
from flowno.core.flow.instrumentation import get_current_flow_instrument
from flowno.core.types import (
    DataGeneration,
    Generation,
    InputPortIndex,
    OutputPortIndex,
    RunLevel,
)
from flowno.utilities.helpers import (
    clip_generation,
    cmp_generation,
    inc_generation,
    parent_generation,
    stitched_generation,
)
from typing_extensions import TypeVarTuple, Unpack, deprecated, override, Protocol


logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_Ts = TypeVarTuple("_Ts")

#: The return type of a single output or multiple output node.
ReturnTupleT_co = TypeVar("ReturnTupleT_co", covariant=True, bound=tuple[object, ...])
_InputType = TypeVar("_InputType")
_ReturnT = TypeVar("_ReturnT")
_Tout = TypeVar("_Tout", covariant=True)

ObjectFinalizedNode: TypeAlias = "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"

# node context protocol for type checking
class NodeContextFactoryProtocol(Protocol):
    def get_current(cls, path: str, node: "FinalizedNode") -> "NodeContext":
        """Get the current node context for the given path."""
        ...

class NodeContext:
    """A user-overridable container for per-node execution context."""
    pass

@dataclass(eq=False)
class SuperNode:
    """
    The SuperNode is a set of nodes that are strongly connected to each
    other. It is used by the cycle detection algorithm.
    """

    head: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"
    members: dict[
        "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]",
        list[InputPortIndex],
    ]  # used to track the internal connections of the super-node

    dependent: "SuperNode | None" = None  # used to build the condensed graph/forest
    dependencies: list["SuperNode"] = field(default_factory=list)  # used to build the condensed graph/forest

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SuperNode):
            return NotImplemented
        return self.head == other.head

    @override
    def __hash__(self) -> int:
        return id(self.head)

    def gather_supernodes(self) -> list["SuperNode"]:
        """
        Simple DFS to collect every SuperNode reachable from `root`.
        """
        visited: set["SuperNode"] = set()
        stack: list["SuperNode"] = [self]
        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                # Each supernode can have multiple dependencies
                for dep in current.dependencies:
                    if dep not in visited:
                        stack.append(dep)
        return list(visited)


@deprecated("Not used")
def _node_id(
    node: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]",
) -> str:
    """
    Return a stable identifier for a node to use in Mermaid.
    """
    return f"N_{node._draft_node.__class__.__name__}{node._instance_id}"


@deprecated("Not used")
def _node_label(
    node: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]",
) -> str:
    """
    Return a short label to display for each node.
    """
    return f'"{node}"'


class OriginalCall(NamedTuple):
    call_signature: inspect.Signature
    call_code: CodeType
    func_name: str
    class_name: str | None = None

    @property
    def signature(self) -> inspect.Signature:
        return self.call_signature

    @property
    def filename(self) -> str:
        return self.call_code.co_filename

    @property
    def lineno(self) -> int:
        return self.call_code.co_firstlineno


class DraftNode(ABC, Generic[Unpack[_Ts], ReturnTupleT_co]):
    """Abstract Base class for all connectable draft nodes in the flow graph.

    DraftNode subclass instance represents a node that can be connected to
    other nodes to form a computational graph. It only handles input/output
    connections. The node must be wrapped in a FinalizedNode to be used in a
    running flow.

    .. warning::
        Do not use this class directly, use the :py:deco:`node <flowno.node>`
        decorator instead

    Examples:
        >>> from flowno import node, FlowHDL
        >>> @node
        ... async def add(a: int, b: int) -> int:
        ...     return a + b
        >>> with FlowHDL() as f:
        ...     f.result = add(1, f.result)
    """

    #: Used by subclasses to set the minimum run level required for each input port
    _minimum_run_level: ClassVar[list[RunLevel]]

    # TODO: See about removing and just reading from _original_call
    #: Used by dynamically generated subclasses in the @node factory
    _default_values: ClassVar[dict[int, object]]

    _original_call: ClassVar[OriginalCall]

    #: Used for debugging and logging
    _instance_counter: ClassVar[int] = 0
    _instance_id: int

    def __init__(self, *args: Unpack[tuple[object, ...]]) -> None:
        self._instance_id = self.increment_instance_counter()
        logger.debug(f"Initializing {self.__class__.__name__}#{self._instance_id} with args {args}")

        self._input_ports: defaultdict[InputPortIndex, DraftInputPort[object]] = defaultdict(DraftInputPort[object])
        self._connected_output_nodes: defaultdict[
            OutputPortIndex,
            list[DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]],
        ] = defaultdict(list)

        max_ports = max(len(args), len(self._minimum_run_level))
        if self._minimum_run_level:
            minimum_run_level = list(self._minimum_run_level) + [0] * (max_ports - len(self._minimum_run_level))
        else:
            minimum_run_level = [0] * max_ports
        for input_port_index in (InputPortIndex(index) for index in range(max_ports)):
            self._input_ports[input_port_index].minimum_run_level = minimum_run_level[input_port_index]

        from .flow_hdl_view import FlowHDLView
        FlowHDLView.register_node(self)

        # loop over each argument and set up the corresponding input port
        for input_connection, arg in (
            (
                DraftInputPortRef[object](
                    cast(DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], self),
                    InputPortIndex(index),
                ),
                arg,
            )
            for index, arg in enumerate(args)
        ):
            logger.debug(f"Initializing {input_connection} with arg {arg} (type={type(arg).__name__})")

            # arg can be None, a DraftNode, a NodeOutputPlaceholder, a
            # NodePlaceholder, an OutputConnection, or a constant

            if arg is None:
                # no connection on this input port. Passing an explicit None
                # indicates that there is a port here, but we want it to be
                # disconnected.
                self._input_ports[input_connection.port_index].connected_output = None

            if isinstance(arg, DraftNode):
                # if a node is passed as an argument, connect the first output
                # port to this input port
                arg.output(0).connect(input_connection)

            elif isinstance(arg, NodePlaceholder):
                # if a node placeholder is passed as an argument, then we can't connect it yet
                # we'll wait until the FlowHDL context is closed to finalize the connections
                self._input_ports[input_connection.port_index].connected_output = arg.output(0)

            elif isinstance(arg, DraftOutputPortRef):
                # f.mynode = MyNode(f.other_node.output(0))
                # an output connection is a fully specified connection to
                # another node's output port. we have no idea what the type of
                # the node connection is assigned to the arg. subclasses or
                # @node class factory overloads can to typechecking.
                cast(DraftOutputPortRef[object], arg).connect(input_connection)

            elif isinstance(arg, OutputPortRefPlaceholder):
                # a node output placeholder is a partially specified connection to another node's output port
                self._input_ports[input_connection.port_index].connected_output = arg
            else:
                # otherwise, it's a constant. Wrap it in a Constant node and connect it.
                constant_node = Constant[object](arg)
                constant_node.output(0).connect(input_connection)

        # DraftNode can be used as a subclass, where `.call()` is overridden,
        # or as a decorator which builds a dynamically generated subclass.

        # * A subclass with a custom `call` method will use defaults from the
        #   call method signature
        # * The node decorator assignes default values to the
        #   cls._default_values class attribute

        # Copy the default values from the source (_default_values or .call
        # parameters) to the input port for uniform access

        if self.__class__._default_values:
            logger.debug(f"{self.__class__.__name__} has _default_values: {self._default_values}")
            for input_port_index, default_value in ((InputPortIndex(i), v) for i, v in self._default_values.items()):
                logger.debug(
                    f"Setting default, {default_value}, for {DraftInputPortRef(cast(DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], self), input_port_index)}"
                )
                self._input_ports[input_port_index].default_value = default_value
        else:
            logger.debug(f"{self.__class__.__name__} has no _default_values, extracting from call method signature")

            # If the _default_values class attribute is not set, use the default values from the call method signature
            call_sig = inspect.signature(self.call)
            call_parameters = call_sig.parameters
            for index, param in enumerate(call_parameters.values()):
                logger.debug(f"Checking {self} parameter {param} for default value")
                default_value: object = param.default  # pyright: ignore[reportAny]
                if default_value is not inspect.Parameter.empty:
                    logger.debug(f"Setting default value for {self} input {index} to {default_value}")
                    self._input_ports[InputPortIndex(index)].default_value = default_value

        for port_index, port in self._input_ports.items():
            input_port_ref = DraftInputPortRef[object](
                cast(DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], self),
                port_index,
            )
            logger.debug(
                (
                    f"Initialized {input_port_ref} "
                    f"with connected_output={port.connected_output}, "
                    f"minimum_run_level={port.minimum_run_level}, "
                    f"default_value={port.default_value}"
                )
            )

    def get_data(self, run_level: RunLevel = 0) -> ReturnTupleT_co:
        raise NotImplementedError

    def increment_instance_counter(self) -> int:
        current_count = self.__class__._instance_counter
        self.__class__._instance_counter += 1
        return current_count

    def output(self, output_port: int) -> "DraftOutputPortRef[object]":
        # TODO: Validate that we are not referencing a port that does not exist. Not sure how.
        return DraftOutputPortRef(
            cast(DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], self),
            OutputPortIndex(output_port),
        )

    def input(self, port_index: int) -> "DraftInputPortRef[object]":
        return DraftInputPortRef(
            cast(DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], self),
            InputPortIndex(port_index),
        )

    @abstractmethod
    def call(
        self, *args: Unpack[_Ts]
    ) -> (
        Coroutine[Any, Any, ReturnTupleT_co]
        | AsyncGenerator[ReturnTupleT_co, None]  # pyright: ignore[reportExplicitAny]
    ):
        raise NotImplementedError

    def accumulate_streamed_data(self, accumulator: ReturnTupleT_co, partial: ReturnTupleT_co) -> ReturnTupleT_co:
        # TODO: add ability to 'override' this in stateful node defiitions
        # TODO: think about allowing different types for differnt run levels
        new_acc = []
        for output_port, output_data in enumerate(partial):
            acc_slice = accumulator[output_port]

            if isinstance(acc_slice, int) and isinstance(output_data, int):
                new_acc.append(acc_slice + output_data)  # pyright: ignore[reportUnknownMemberType]
            elif isinstance(acc_slice, float) and isinstance(output_data, float):
                new_acc.append(acc_slice + output_data)  # pyright: ignore[reportUnknownMemberType]
            elif isinstance(acc_slice, str) and isinstance(output_data, str):
                new_acc.append(acc_slice + output_data)  # pyright: ignore[reportUnknownMemberType]
            else:
                raise NotImplementedError(
                    "You must implement accumulate_streamed_data for non-simple data types, or manually raise StopAsyncIteration(final_value) when the stream is complete."
                )
        new_acc = cast(ReturnTupleT_co, tuple(new_acc))  # pyright: ignore[reportUnknownArgumentType]

        return new_acc

    @override
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}#{self._instance_id}"

    def get_output_nodes(
        self,
    ) -> list["DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]"]:
        """Get all nodes connected to this node's outputs."""
        return [node for nodes in self._connected_output_nodes.values() for node in nodes]

    def get_input_nodes(
        self,
    ) -> list["DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]"]:
        """Get all nodes connected to this node's inputs."""
        nodes: list[DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]] = []
        for input_port in self._input_ports.values():
            if input_port.connected_output is not None and isinstance(input_port.connected_output.node, DraftNode):
                nodes.append(input_port.connected_output.node)
        return nodes

    def _blank_finalized(self) -> "FinalizedNode[Unpack[_Ts], ReturnTupleT_co]":
        """Convert this draft node into a finalized node without connections."""
        return FinalizedNode(
            self._original_call,
            self._instance_id,
            dict(),
            dict(),
            self,
        )


class FinalizedNode(Generic[Unpack[_Ts], ReturnTupleT_co]):
    """The finalized node with valid connections to other nodes. Do not
    explicitly create or subclass `FinalizedNode`.

    """

    _original_call: OriginalCall
    _instance_id: int
    _input_ports: dict[InputPortIndex, "FinalizedInputPort[object]"]
    _connected_output_nodes: dict[
        OutputPortIndex,
        list["FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"],
    ]
    _barrier0: CountdownLatch
    _barrier1: CountdownLatch
    _draft_node: DraftNode[Unpack[_Ts], ReturnTupleT_co]

    # TODO: We only ever read the highest clipped generation data for each run
    # level. Replace with a forgetful datastructure
    _data: dict[DataGeneration, ReturnTupleT_co]

    def __init__(
        self,
        original_call: OriginalCall,
        instance_id: int,
        input_ports: dict[InputPortIndex, "FinalizedInputPort[object]"],
        connected_output_nodes: dict[
            OutputPortIndex,
            list["FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"],
        ],
        draft: DraftNode[Unpack[_Ts], ReturnTupleT_co],
    ):
        self._original_call = original_call
        self._instance_id = instance_id
        self._input_ports = input_ports
        self._connected_output_nodes = connected_output_nodes
        self._draft_node = draft
        self._barrier0 = CountdownLatch(0)
        self._barrier1 = CountdownLatch(0)

        self._data = dict()

    def __getattr__(self, name: str) -> Any:
        """
        Delegate attribute lookups to the underlying draft node if this
        class does not have the attribute itself. This allows code like
        `f.toggle.count` to reach the user-defined class attribute.
        """
        # If FinalizedNode itself has the attribute, return it:
        if name in self.__dict__:
            return self.__dict__[name]
        # Otherwise, delegate to the draft node instance:
        return getattr(self._draft_node, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Delegate attribute writes to the underlying draft node if it's
        not part of FinalizedNode's own internal attributes.
        """
        # If it's one of our known fields or starts with underscore, set it here:
        if name.startswith("_") or name in self.__dict__ or hasattr(type(self), name):
            super().__setattr__(name, value)
        else:
            setattr(self._draft_node, name, value)

    def output(self, output_port: int) -> "FinalizedOutputPortRef[object]":
        # TODO: Validate that we are not referencing a port that does not exist. Not sure how.
        return FinalizedOutputPortRef(
            cast(FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], self),
            OutputPortIndex(output_port),
        )

    def input(self, port_index: int) -> "FinalizedInputPortRef[object]":
        return FinalizedInputPortRef(
            cast(FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]], self),
            InputPortIndex(port_index),
        )

    def get_output_nodes(
        self,
    ) -> list["FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"]:
        """Get all nodes connected to this node's outputs."""
        return [node for nodes in self._connected_output_nodes.values() for node in nodes]

    def get_output_nodes_by_run_level(self, run_level: RunLevel) -> list["FinalizedInputPort[object]"]:
        """
        Returns a list of input ports (FinalizedInputPort objects) from consumer nodes that are connected
        to this node, filtered by the specified run level.

        Each input port is included once per connection. That is, if the same consumer is connected
        multiple times (or via different output ports) with a minimum_run_level equal to the specified run_level,
        it will appear once for each such connection.

        Args:
            run_level (RunLevel): The desired run level (for example, 0 for final data, 1 for partial/streaming updates).

        Returns:
            list[FinalizedInputPort[object]]: A list of input ports on consumer nodes that are connected to self and
                                              have the specified minimum_run_level.
        """
        ret: list[FinalizedInputPort[object]] = []

        # Iterate over all output ports and their connected consumer nodes.
        for output_port, consumer_nodes in self._connected_output_nodes.items():
            # For each consumer node connected on this output port...
            for consumer in consumer_nodes:
                # Iterate over each input port on the consumer.
                for input_port_index, consumer_input in consumer._input_ports.items():
                    # Skip this input port if it is not connected.
                    if consumer_input.connected_output is None:
                        continue
                    # Check that this input port is connected specifically to the current output port.
                    if (
                        consumer_input.connected_output.node is self
                        and consumer_input.connected_output.port_index == output_port
                    ):
                        # Check if this input port expects data at the specified run level.
                        if consumer_input.minimum_run_level == run_level:
                            ret.append(consumer_input)

        return ret

    def has_default_for_input(self, input_port_index: InputPortIndex) -> bool:
        input_port = self._input_ports[input_port_index]

        if hasattr(input_port, "default_value") and input_port.default_value is not inspect.Parameter.empty:
            logger.debug(f"{self} input port {input_port_index} has a default value: {input_port.default_value}")
            return True
        logger.debug(f"{self} input port {input_port_index} does NOT have a default value")
        return False

    @property
    def generation(self) -> Generation:
        return max(self._data.keys(), key=cmp_to_key(cmp_generation), default=None)

    def get_data(self, run_level: RunLevel = 0) -> ReturnTupleT_co | None:
        """Get the most recent data produced by the node at the specified run level.

        Args:
            run_level: The run level to retrieve data for (default: 0)

        Returns:
            The tuple of data produced by this node, or None if no data is available
        """
        if self.generation is None:
            return None
        if len(self.generation) - 1 > run_level:
            requested_generation = list(self.generation[: run_level + 1])
            requested_generation[run_level] -= 1  # truncating is data in the future
            if tuple(requested_generation) not in self._data:
                return None
            return self._data[tuple(requested_generation)]
        if len(self.generation) - 1 < run_level:
            return None

        return self._data[self.generation]

    async def count_down_upstream_latches(self, defaulted_inputs: list[InputPortIndex]) -> None:
        """Count down upstream node barriers for non-defaulted connected inputs."""
        for input_port_index, input_port in self._input_ports.items():
            if input_port.connected_output is None or input_port_index in defaulted_inputs:
                continue
            # Skip streaming inputs - they read run_level=1 data and count down barrier1 in Stream.__anext__()
            if input_port.minimum_run_level > 0:
                continue
            upstream_node = input_port.connected_output.node
            try: 
                await upstream_node._barrier0.count_down(exception_if_zero=True)
            except Exception as e:
                logger.warning(f"count_down_upstream_latches({self}, {defaulted_inputs})")
                logger.warning(f"Error counting down upstream latches: {e}")
                logger.warning(f"Upstream node: {upstream_node}")
                logger.warning(f"Input port index: {input_port_index}")

    @final
    def push_data(self, data: ReturnTupleT_co | None, run_level: RunLevel = 0) -> None:
        logger.debug(f"push_data({self}, {data}, run_level={run_level})")
        new_generation = inc_generation(self.generation, run_level)
        logger.info(
            f"{self} advanced to generation {new_generation} with data={data}",
            extra={"tag": "flow"},
        )

        logger.debug(f"{self}.data[{new_generation}] = {repr(data)}")
        self._data[tuple(new_generation)] = data

    def _get_maximum_input_generation(self) -> Generation:
        """Return the highest generation of the connected inputs using
        predicate `cmp_generation`."""
        max_input_generation = None
        for _input_port, input_data in self._input_ports.items():
            if input_data.connected_output is None:
                continue
            input_node = input_data.connected_output.node
            input_gen = input_node.generation
            if cmp_generation(input_gen, max_input_generation) > 0:
                max_input_generation = input_gen
        return max_input_generation

    def get_inputs_with_le_generation_clipped_to_minimum_run_level(
        self,
    ) -> "list[FinalizedInputPort[object]]":
        """
        Get the input nodes that should be resolved before this node should run,
        considering the minimum run level required for each input.
        
        For each input connection, the following steps are performed:
        
        - Clip the input node's generation based on the input port's minimum run level.
        - Add the stitch value to the clipped generation.
        - Compare the clipped and stitched generation with this node's current generation.
        
            - The input is considered stale and needs to be resolved if the clipped generation is less than or equal to this node's generation.
        

        Returns:
            List[InputConnection]: A list of input connections that are stale and  and need to be resolved before this node can run.


        """
        stale_inputs: list[FinalizedInputPort[object]] = []

        for my_input_port_index, input_port in self._input_ports.items():
            placeholder = input_port.connected_output

            if placeholder is None:
                # No connection on this input port; skip.
                continue

            input_node = placeholder.node

            if isinstance(input_node, NodePlaceholder):
                # Connection is still a placeholder; skip.
                continue

            # Clip the input node's generation based on the minimum run level required.
            clipped_gen: Generation = clip_generation(input_node.generation, input_port.minimum_run_level)

            # Add the stitch value to the clipped generation.
            clipped_gen = stitched_generation(clipped_gen, input_port.stitch_level_0)

            # Compare the clipped generation with this node's current generation.
            # If clipped_gen <= self.generation, the input is stale.
            if cmp_generation(clipped_gen, self.generation) <= 0:
                stale_inputs.append(input_port)

        return stale_inputs

    def __repr__(self) -> str:
        name: str
        if self._original_call.class_name:
            name = self._original_call.class_name
        else:
            name = self._original_call.func_name
        return f"{name}#{self._instance_id}"

    class GatheredInputs(NamedTuple):
        positional_args: "tuple[object | Stream[object], ...]"
        defaulted_ports: list[InputPortIndex]

    def call(
        self, *args: Unpack[_Ts]
    ) -> (
        Coroutine[Any, Any, ReturnTupleT_co]
        | AsyncGenerator[ReturnTupleT_co, None]  # pyright: ignore[reportExplicitAny]
    ):
        """Delegate call to the draft node implementation"""
        return self._draft_node.call(*args)

    def gather_inputs(self) -> GatheredInputs:
        """Gather the inputs for the node.

        For input ports that request non-streaming data, the last data produced
        by the input node is used. For input ports that request streaming data,
        a Stream object is used with reference to self.

        Returns:
            tuple[object | Stream[object], ...]: The tuple of inputs for the
            node to be passed as args to the call method.
        """
        # TODO: move this to finalized node class
        inputs: dict[InputPortIndex, object | Stream[object]] = dict()

        defaulted_ports: list[InputPortIndex] = []

        for input_port_index, input_port in self._input_ports.items():
            logger.debug(f"Gathering input data for {self.input(input_port_index)}")

            if input_port.connected_output is None:
                if self.has_default_for_input(input_port_index):
                    # The input is disconnected but has a default. Use that and
                    # skip to next input.
                    inputs[input_port_index] = input_port.default_value
                    continue
                else:
                    # The input is disconnected but has no default value.
                    raise MissingDefaultError(self, input_port_index)
            # input_port is connected
            # inputs[input_port_index] not set

            input_node = input_port.connected_output.node
            this_port_defaulted = False

            run_level = input_port.minimum_run_level
            last_data = input_node.get_data(run_level=run_level)
            if last_data is None:
                # The input is disconnected or the node is being 'forced'
                #
                if self.has_default_for_input(input_port_index):
                    individual_last_data = input_port.default_value
                    defaulted_ports.append(input_port_index)
                    this_port_defaulted = True
                    logger.info(
                        f"While gathering input data for {DraftInputPortRef(self, input_port_index)}, using default value {individual_last_data}",
                        extra={"tag": "flow"},
                    )
                else:
                    raise MissingDefaultError(self, input_port_index)
            else:
                # pick out just the output port data we need
                individual_last_data = last_data[input_port.connected_output.port_index]

            if input_port.minimum_run_level > 0 and not this_port_defaulted:
                inputs[input_port_index] = Stream(self.input(input_port_index), input_port.connected_output)
            else:
                inputs[input_port_index] = individual_last_data

            logger.debug(f"Input data for {DraftInputPortRef(self, input_port_index)}: {inputs[input_port_index]}")

        # check for missing non-defaulted inputs
        positional_args: list[object | Stream[object]] = list()
        if inputs:
            for input_port_index in map(InputPortIndex, range(max(inputs.keys()) + 1)):
                if input_port_index in inputs:
                    positional_args.append(inputs[input_port_index])
                else:
                    raise MissingDefaultError(self, input_port_index)
        return self.GatheredInputs(tuple(positional_args), defaulted_ports)
    def debug_print(self) -> None:
        """
        Print detailed debug information about this node, including its inputs, outputs, and data.
        """
        print(f"FinalizedNode: {self}")
        print(f"  Instance ID: {self._instance_id}")
        print(f"  Original Call: {self._original_call}")
        print(f"  Inputs:")
        for idx, port in self._input_ports.items():
            print(f"    Input {idx}:")
            print(f"      Connected Output: {port.connected_output}")
            print(f"      Minimum Run Level: {port.minimum_run_level}")
            print(f"      Default Value: {getattr(port, 'default_value', None)}")
            print(f"      Stitch Level 0: {getattr(port, 'stitch_level_0', None)}")
        print(f"  Connected Output Nodes:")
        for out_idx, nodes in self._connected_output_nodes.items():
            print(f"    Output {out_idx}: {[str(n) for n in nodes]}")
        print(f"  Data Generations:")
        for gen, data in self._data.items():
            print(f"    Generation {gen}: {data}")
        print(f"  Current Generation: {self.generation}")

class Stream(Generic[_InputType], AsyncIterator[_InputType]):
    """A stream of values from one node to another.

    Streams connect nodes that produce multiple values over time (run_level > 0)
    to consuming nodes. They act as async iterators that yield values as they
    become available.

    Type Parameters:
        _InputType: The type of data being streamed
    """

    input: "FinalizedInputPortRef[_InputType]"
    output: "FinalizedOutputPortRef[_InputType]"

    def __init__(
        self,
        input: "FinalizedInputPortRef[_InputType]",
        output: "FinalizedOutputPortRef[_InputType]",
    ) -> None:
        super().__init__()
        self.input = input
        self.output = output
        self._last_consumed_generation: Generation = None
        self.run_level: RunLevel = 1
        self._last_consumed_parent_generation: Generation = None
        self._cancelled: bool = False
        self._cancel_acknowledged: bool = False

    @override
    def __aiter__(self) -> AsyncIterator[_InputType]:
        get_current_flow_instrument().on_stream_start(self)
        return self

    @override
    def __repr__(self) -> str:
        return f"Stream({self.output}->{self.input}, last_consumed={self._last_consumed_generation}, last_consumed_parent={self._last_consumed_parent_generation}, run_level={self.run_level})"

    @coroutine
    def cancel(self) -> Generator["StreamCancelCommand", None, None]:
        """Cancel this stream, causing the producer to receive StreamCancelled on next yield."""
        if self._cancelled:
            return  # Already cancelled
        
        self._cancelled = True
        logger.info(f"Stream {self} cancellation requested", extra={"tag": "flow"})
        
        # Yield command to event loop to inject exception into producer        
        yield StreamCancelCommand(
            stream=self,
            producer_node=self.output.node,
            consumer_input=self.input
        )
        
    @override
    async def __anext__(self) -> _InputType:
        logger.debug(f"calling __anext__({self})")

        # Check if stream is cancelled
        if self._cancelled:
            logger.debug(f"Stream {self} is cancelled, raising StopAsyncIteration")
            raise StopAsyncIteration("Stream was cancelled")
        
        def get_clipped_stitched_gen():
            stitch_0 = self.input.node._input_ports[self.input.port_index].stitch_level_0
            return clip_generation(
                stitched_generation(self.output.node.generation, stitch_0), run_level=self.run_level
            )

        while (
            cmp_generation(
                get_clipped_stitched_gen(),
                self._last_consumed_generation,
            )
            <= 0
        ):
            logger.debug(
                (
                    f"{self.output.node}'s generation, "
                    f"when clipped {clip_generation(self.output.node.generation, run_level=self.run_level)}, "
                    f"and stitched {get_clipped_stitched_gen()}, "
                    f"is less than or equal to the last consumed generation {self._last_consumed_generation}"
                    f", requesting new data."
                )
            )
            await _node_stalled(self.input, self.output.node)
        logger.debug(
            f"{self.output.node}'s generation, when clipped and stitched, is greater than the last consumed generation, continuing."
        )
        logger.debug(f"__anext__({self}): continuing")
        if (
            self._last_consumed_generation is not None
            and parent_generation(self.output.node.generation) != self._last_consumed_parent_generation
        ):
            logger.debug(
                (
                    f"Parent generation changed from {self._last_consumed_parent_generation} "
                    f"to {parent_generation(self.output.node.generation)} "
                    f"indicating the stream is complete or restarted."
                )
            )
            logger.info(f"Stream {self} is complete or restarted.", extra={"tag": "flow"})
            get_current_flow_instrument().on_stream_end(self)
            raise StopAsyncIteration

        self._last_consumed_generation = get_clipped_stitched_gen()
        self._last_consumed_parent_generation = parent_generation(self.output.node.generation)

        data_tuple = self.output.node.get_data(run_level=self.run_level)
        assert data_tuple is not None
        data = cast(_InputType, data_tuple[self.output.port_index])

        logger.debug(f"__anext__({self}) returning {repr(data)}")
        logger.info(
            f"Stream {self} consumed data {repr(data)}",
            extra={"tag": "flow"},
        )

        with get_current_flow_instrument().on_barrier_node_read(self.output.node, 1):
            try:
                await self.output.node._barrier1.count_down(exception_if_zero=True)  # TODO: check if this needs to be async-awaited
            except Exception as e:
                logger.warning(f"Stream {self} anext count_down error: {e}")
                logger.warning(f"Node: {self.output.node}")
                logger.warning(f"Input port index: {self.input.port_index}")

        # Instrumentation: Stream processed next item
        get_current_flow_instrument().on_stream_next(self, data)

        return data


@dataclass
class StalledNodeRequestCommand(Command):
    stalled_input: "FinalizedInputPortRef[object]"
    stalling_node: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]"


@coroutine
def _node_stalled(
    stalled_input: "FinalizedInputPortRef[Any]",
    stalling_node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
) -> Generator["StalledNodeRequestCommand", None, None]:

    logger.info(
        f"{stalled_input} is stalled. Requesting new data from {stalling_node}.",
        extra={"tag": "flow"},
    )

    return (yield StalledNodeRequestCommand(stalled_input, stalling_node))


@dataclass
class NodePlaceholder:
    """Placeholder for a node defined on a FlowHDL context instance.

    Examples:
        >>> with FlowHDL() as flow:
        ...     flow.node1 = DummyNode()
        ...     assert isinstance(flow.node1, Node)
        ...     assert isinstance(flow.node2, NodePlaceholder)
        ...     print(flow.node2.name) # prints "node2"
        ...     assert isinstance(flow.node3[OutputPortIndex(0)], NodeOutputPlaceholder)
    """

    name: str

    def output(self, output_port: OutputPortIndex | int) -> "OutputPortRefPlaceholder[object]":
        return OutputPortRefPlaceholder[object](self, OutputPortIndex(output_port))


@dataclass
class OutputPortRefPlaceholder(Generic[_ReturnT]):
    """Placeholder for a specific output port of a NodePlaceholder.
    """
    
    node: NodePlaceholder
    port_index: OutputPortIndex

    @override
    def __repr__(self) -> str:
        return f"{self.node}.output({self.port_index})"


@dataclass
class DraftOutputPortRef(Generic[_Tout]):
    """Represents the an output port on a node (the data producer).

    Type Parameters:
        _T : A phantom type. The `port_index` output of `node.call(...)` should be `_T`.
    """

    node: DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    port_index: OutputPortIndex

    @override
    def __repr__(self) -> str:
        return f"{self.node}.output({self.port_index})"

    def connect(
        self,
        target: "DraftInputPortRef[_Tout]",
    ):
        """
        Wires this output to the given target's input.
        Internally, record that data flows
        source_node.output(port_index) -> target_node.input(port_index)
        """
        logger.info(f"Connecting {self} -> {target}")

        self.node._connected_output_nodes[self.port_index].append(target.node)
        target.node._input_ports[target.port_index].connected_output = cast(DraftOutputPortRef[object], self)

    def _finalize(
        self,
        final_by_draft: dict[
            DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]],
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ],
    ):
        return FinalizedOutputPortRef[_Tout](node=final_by_draft[self.node], port_index=self.port_index)


@dataclass
class DraftInputPortRef(Generic[_T]):
    """Represents an input port of a node (the data consumer).

    Type Parameters:
        _T : Phantom type. The `port_input` arg to `node.call(...)` should be `_T`.
    """

    node: DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    port_index: InputPortIndex

    @override
    def __repr__(self) -> str:
        return f"{self.node}.input({self.port_index})"


@dataclass
class FinalizedOutputPortRef(Generic[_T]):
    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    port_index: OutputPortIndex

    @override
    def __repr__(self) -> str:
        return f"{self.node}.output({self.port_index})"


@dataclass
class FinalizedInputPortRef(Generic[_T]):
    node: FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]
    port_index: InputPortIndex

    @override
    def __repr__(self) -> str:
        return f"{self.node}.input({self.port_index})"


@dataclass(kw_only=True)
class DraftInputPort(Generic[_T]):
    connected_output: DraftOutputPortRef[_T] | OutputPortRefPlaceholder[_T] | None = None
    minimum_run_level: RunLevel = 0
    default_value: object | type[inspect.Parameter.empty] = inspect.Parameter.empty

    def _finalize(
        self,
        port_index: InputPortIndex,
        final_by_draft: dict[
            DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]],
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ],
    ) -> "FinalizedInputPort[_T]":
        if isinstance(self.connected_output, OutputPortRefPlaceholder):
            raise AttributeError(
                "Attempted to finalize an input port, {self} that still has a placeholder connected_output."
            )

        if self.connected_output is None:
            finalized_connected_output = None
        else:
            finalized_connected_output = self.connected_output._finalize(final_by_draft)

        return FinalizedInputPort[_T](
            port_index=port_index,
            connected_output=finalized_connected_output,
            minimum_run_level=self.minimum_run_level,
            default_value=self.default_value,
            stitch_level_0=0,
        )


@dataclass(kw_only=True)
class FinalizedInputPort(Generic[_T]):
    port_index: InputPortIndex
    connected_output: FinalizedOutputPortRef[_T] | None = None
    minimum_run_level: RunLevel = 0
    default_value: object | type[inspect.Parameter.empty] = inspect.Parameter.empty
    stitch_level_0: int = 0


class Constant(DraftNode[(), tuple[_T]]):
    """
    A node that produces a constant value of type _T.

    Parameters
    ----------
    value : _T
        The constant value produced by the node.
    """

    value: _T

    # Since we have zero inputs, the “minimum_run_level” list is empty
    _minimum_run_level: ClassVar[list[RunLevel]] = []

    # No default values are needed for a constant’s inputs (it has none)
    _default_values: ClassVar[dict[int, object]] = {}

    # Provide a class-level OriginalCall so that FinalizedNode
    # can figure out signature info, filename, lineno, etc.
    _original_call: ClassVar[OriginalCall] = OriginalCall(
        inspect.signature(lambda: None),  # a dummy signature; or use call’s
        (lambda: None).__code__,  # a dummy code object; or use call’s
        func_name="call",
        class_name="Constant",
    )

    def __init__(self, value: _T) -> None:
        # Our node has no inputs, so just call super().__init__() with no args
        super().__init__()
        self.value = value

        # If you want to make _original_call match exactly your real call() method,
        # you can override it here with the real code object and signature:
        self.__class__._original_call = OriginalCall(
            inspect.signature(self.call),
            self.call.__code__,
            func_name="call",
            class_name=self.__class__.__name__,
        )

    @override
    async def call(self) -> tuple[_T]:
        """
        Produce the single-value tuple containing our constant.
        """
        return (self.value,)


# >>>>>>>> ChatGPT generated crap


def build_signature_display(
    oc: "OriginalCall",
    required_input_ports: list["InputPortIndex"],
) -> str:
    """
    Return a multi-line string that shows either:
      1) ClassName.call(...) in an abbreviated form, or
      2) func_name(...) in a traditional inline form

    With underlines marking which parameters are missing defaults.

    """
    # Pull out the parameters
    parameters = list(oc.signature.parameters.items())
    # Decide if 'self' is the first parameter
    skip_self = len(parameters) > 0 and parameters[0][0] == "self"

    # Distinguish the "class's call method" case from a normal function
    if oc.class_name and oc.func_name == "call":
        # e.g.  MyNode.call
        #       (x: int, y: str=...)
        line_1 = f"  class {oc.class_name}:"
        line_2, underline_2 = build_abbreviated_signature(parameters, required_input_ports, skip_self)
        # Indent 'async def call' by four spaces
        line_2 = f"      async def {oc.func_name}(self, {line_2}): ..."
        return f"{line_1}\n{line_2}\n{' '*(len(oc.func_name)+23)}{underline_2}"
    else:
        # Normal function style:  func_name(x: int, y: str=...)
        signature_line, param_positions = build_inline_signature(
            oc.func_name, parameters, required_input_ports, skip_self
        )
        underline_line = build_underline_line(signature_line, param_positions)
        return f"  async def {signature_line}\n{' ' * 12}{underline_line}"


def build_abbreviated_signature(
    parameters: list[tuple[str, inspect.Parameter]],
    required_input_ports: list["InputPortIndex"],
    skip_self: bool,
) -> tuple[str, str]:
    """
    Construct just the parenthesized parameter list, skipping self if needed.
    Returns the line plus a line of dashes/underlines for missing-default params.
    """
    # If skipping self, we offset all required_input_ports by one
    # to align them with actual param indices.
    # Or you can treat real_index carefully in a loop.
    param_strings = []
    param_positions = []
    signature_text = ""
    current_length = len(signature_text)

    for i, (pname, pval) in enumerate(parameters):
        # If skip_self and this is the 0th parameter, omit it.
        if skip_self and i == 0:
            continue

        # Figure out the real input-port index
        real_index = i if not skip_self else (i - 1)
        underline_needed = real_index in required_input_ports

        # Build text for this parameter
        param_text = build_param_text(pname, pval)
        start_pos = current_length
        signature_text += param_text
        end_pos = start_pos + len(param_text)
        param_positions.append((start_pos, end_pos, underline_needed))

        current_length += len(param_text)
        # Add comma if not last visible param
        if i < len(parameters) - 1:
            signature_text += ", "
            current_length += 2

    signature_text += ""
    underline_line = build_underline_line(signature_text, param_positions)

    return signature_text, underline_line


def build_inline_signature(
    func_name: str,
    parameters: list[tuple[str, inspect.Parameter]],
    required_input_ports: list["InputPortIndex"],
    skip_self: bool,
) -> tuple[str, list[tuple[int, int, bool]]]:
    """
    Build something like:  func_name(x: int=1, y: str)
    Returns the signature string and param_positions for underlining.
    """
    signature_line = f"{func_name}("
    param_positions = []
    current_length = len(signature_line)

    for i, (pname, pval) in enumerate(parameters):
        if skip_self and i == 0:
            # Just show 'self' plainly or skip it entirely. Usually you'd skip it in the signature.
            # If you prefer to omit it, comment out or adapt logic here.
            continue

        real_index = i if not skip_self else (i - 1)
        underline_needed = real_index in required_input_ports

        param_text = build_param_text(pname, pval)
        start_pos = current_length
        signature_line += param_text
        end_pos = start_pos + len(param_text)
        param_positions.append((start_pos, end_pos, underline_needed))

        current_length = len(signature_line)
        if i < len(parameters) - 1:
            signature_line += ", "
            current_length += 2

    signature_line += ")"
    return signature_line, param_positions


def build_param_text(param_name: str, param: inspect.Parameter) -> str:
    """
    Return a string representation of one parameter, e.g. `x: int=5`.
    """
    annotation = param.annotation if param.annotation != inspect._empty else "Any"
    if annotation == str:
        annotation = "str"
    elif annotation == int:
        annotation = "int"
    elif annotation == float:
        annotation = "float"

    if param.default == inspect.Parameter.empty:
        return f"{param_name}: {annotation}"
    else:
        return f"{param_name}: {annotation} = {param.default}"


def build_underline_line(signature_line: str, param_positions: list[tuple[int, int, bool]]) -> str:
    """
    Create a line of spaces, with dashes marking the parameters that need defaults.
    """
    underline_chars = [" "] * len(signature_line)
    for start, end, needed in param_positions:
        if needed:
            for idx in range(start, end):
                underline_chars[idx] = "-"
    return "".join(underline_chars)


def format_missing_defaults(
    node: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]",
    required_input_ports: list["InputPortIndex"],
) -> str:
    """
    Produce a message describing which parameters of a node must have default
    values. If the node's original call is from a class's `call` method, display
    an abbreviated signature with the class name in a separate line. Otherwise,
    display a more traditional function signature inline.

    The final message includes underlines for each parameter index found in
    required_input_ports.
    """
    oc = node._original_call
    # Gather basic info
    filename, lineno = oc.filename, oc.lineno

    # Build the special or normal signature lines (and underline helpers)
    signature_block = build_signature_display(oc, required_input_ports)

    # Assemble and return the final error message
    return (
        f"  {node} must have defaults for EACH/ALL the underlined parameters:\n"
        f"  Defined at {filename}:{lineno}\n"
        f"  Full Signature:\n"
        f"{signature_block}"
    )


# <<<<<<<<


class StreamCancelled(Exception):
    """Raised when a stream consumer cancels the stream."""
    def __init__(self, stream: "Stream[Any]", message: str = "Stream was cancelled by consumer"):
        self.stream = stream
        super().__init__(message)


class MissingDefaultError(Exception):
    @overload
    def __init__(
        self,
        node: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]",
        input_index: InputPortIndex,
    ) -> None: ...

    @overload
    def __init__(self, node: "SuperNode") -> None: ...

    def __init__(
        self,
        node: "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]] | SuperNode",
        input_index: InputPortIndex | None = None,
    ):
        if not isinstance(node, FinalizedNode):
            assert input_index is None
            missing_info: dict[
                "FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]]",
                list[InputPortIndex],
            ] = {}

            for node, internal_input_ports in node.members.items():
                for internal_input_port in internal_input_ports:
                    if node.has_default_for_input(internal_input_port):
                        continue
                    else:
                        if node not in missing_info:
                            missing_info[node] = []
                        missing_info[node].append(internal_input_port)

            full_message = (
                "Detected a cycle without default values. You must add defaults to the indicated arguments for at least ONE of the following nodes:\n"
                + "\nOR\n".join(
                    format_missing_defaults(node, input_ports) for node, input_ports in missing_info.items()
                )
            )
            super().__init__(full_message)

        else:
            assert input_index is not None
            super().__init__(format_missing_defaults(node, [input_index]))


# Type aliases for common node types
ObjectDraftNode = DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]
AnyNode = DraftNode[Unpack[tuple[Any, ...]], tuple[Any, ...]]

__all__ = [
    "DraftNode",
    "ObjectDraftNode",
    "AnyNode",
    "NodePlaceholder",
    "DraftInputPortRef",
    "DraftOutputPortRef",
    "Stream",
    "StreamCancelled",
    "OutputPortRefPlaceholder",
]
