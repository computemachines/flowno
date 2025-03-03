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

from flowno.core.flow.flow import Flow
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


class FlowHDL:
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

    KEYWORDS: ClassVar[list[str]] = ["KEYWORDS", "run_until_complete"]
    """Keywords that should not be treated as nodes in the graph."""

    _is_finalized: bool

    def __init__(self) -> None:
        self._is_finalized = False
        self._nodes: dict[str, Any] = {}  # pyright: ignore[reportExplicitAny]
        self._flow: Flow = Flow(is_finalized=False)

    def __enter__(self: Self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Finalize the graph when exiting the context by calling :meth:`_finalize`."""
        self._finalize()
        return False

    @override
    def __setattr__(self, key: str, value: Any) -> None:
        """Override the default attribute setter to store nodes in a dictionary.

        Ignores attributes starting with an underscore or in the KEYWORDS list.
        """

        # Allow setting the _is_finalized attribute (in __init__)
        if key.startswith("_") and not key in self.__class__.KEYWORDS:
            return super().__setattr__(key, value)
        else:
            self._nodes[key] = value

    @override
    def __getattribute__(self, key: str) -> NodePlaceholder:
        """
        Override the default attribute getter to return a placeholder for
        undefined attributes.

        Treats attributes starting with an underscore or in the KEYWORDS list
        as normal attributes.
        """

        if key.startswith("_") or key in self.__class__.KEYWORDS:
            return super().__getattribute__(key)
        elif key in self._nodes:
            return self._nodes[key]
        else:
            raise AttributeError(f'Attribute "{key}" not found')

    def __getattr__(self, key: str) -> Any:
        if self._is_finalized:
            raise AttributeError(f'Attribute "{key}" not found')
        return NodePlaceholder(key)

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

    def _finalize(self) -> None:
        """Finalize the graph by replacing connections to placeholders with
        connections to the actual nodes.

        Example: Out of order definition of nodes is allowed, as long as the
        connections are fully defined before the graph is finalized.

        >>> with FlowHDL() as f:
        ...     hdl.a = Node1(f.b)
        ...     hdl.b = Node2()
        """
        logger.info("Finalizing FlowHDL")

        # loop over the members of the FlowHDL instance
        # Replace all OutputPortRefPlaceholders with actual DraftOutputPortRefs
        for node_name, unknown_node in self._nodes.items():
            if not isinstance(unknown_node, DraftNode):
                logger.warning("An unexpected object was assigned as an attribute to the FlowHDL context.")
                continue
            draft_node = cast(DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], unknown_node)

            # DraftInputPorts can have OutputPortRefPlaceholders or DraftOutputPortRefs
            # Step 1) Replace placholders with drafts
            for input_port_index, input_port in draft_node._input_ports.items():
                input_port_ref = DraftInputPortRef[object](draft_node, input_port_index)

                if input_port.connected_output is None:
                    if input_port.default_value != inspect.Parameter.empty:
                        logger.info(f"{input_port_ref} is not connected and but has a default value")
                        continue
                    else:
                        # TODO: Use the same underlined format as supernode.py
                        raise AttributeError(f"{input_port_ref} is not connected and has no default value")

                connected_output = input_port.connected_output

                if isinstance(connected_output, OutputPortRefPlaceholder):
                    # validate that the placeholder has been defined on the FlowHDL instance
                    if connected_output.node.name not in self._nodes:
                        raise AttributeError(
                            (
                                f"Node {connected_output.node.name} is referenced, but has not been defined. "
                                f"Cannot connect {input_port} to non-existent node {connected_output.node.name}"
                            )
                        )
                    output_source_node = self._nodes[connected_output.node.name]

                    # if the placeholder has been defined on the FlowHDL instance but is not a DraftNode, raise an error
                    if not isinstance(output_source_node, DraftNode):
                        raise AttributeError(
                            (
                                f"Attribute {connected_output.node.name} is not a DraftNode. "
                                f"Cannot connect {node_name} to non-DraftNode {connected_output.node.name}"
                            )
                        )

                    # the placeholder was defined on the FlowHDL instance and is a DraftNode, so connect the nodes
                    logger.debug(f"Connecting {output_source_node} to {input_port}")
                    output_source_node.output(input_port.connected_output.port_index).connect(input_port_ref)

        final_by_draft: dict[
            DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]],
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ] = dict()

        # traverse the entire graph, creating blank finalized nodes
        visited: set[DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]] = set()

        def visit_node(draft_node: DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]]) -> None:
            logger.debug(f"{draft_node} Visiting")
            if draft_node in visited:
                logger.debug(f"{draft_node} Already visited")
                return

            visited.add(draft_node)
            finalized_node = draft_node._blank_finalized()
            # finalized_node has empty _input_ports and _connected_output_nodes
            final_by_draft[draft_node] = finalized_node
            self._flow.add_node(finalized_node)

            for downstream_node in draft_node.get_output_nodes():
                visit_node(downstream_node)
            for upstream_node in draft_node.get_input_nodes():
                visit_node(upstream_node)

        logger.debug("DFS Traversing the flow graph to register nodes with the flow.")
        for draft_node in self._nodes.values():
            if isinstance(draft_node, DraftNode):
                visit_node(draft_node)

        # Now I need to fill in the empty _input_ports and _connection_output_ports
        for draft_node, finalized_node in final_by_draft.items():
            finalized_node._input_ports = {
                index: draft_input_port._finalize(index, final_by_draft)
                for index, draft_input_port in draft_node._input_ports.items()
            }
            finalized_node._connected_output_nodes = {
                index: [final_by_draft[connected_draft] for connected_draft in connected_drafts]
                for index, connected_drafts in draft_node._connected_output_nodes.items()
            }

        # overwrite self._nodes[name] with the finalized node
        for name, obj in self._nodes.items():
            if isinstance(obj, DraftNode):
                self._nodes[name] = final_by_draft[obj]

        self._is_finalized = True
        logger.debug("Finished Finalizing FlowHDL into Flow")
