import inspect
import logging
from types import TracebackType
from typing import Any, ClassVar, TypeVar, cast

from flowno.core.flow.flow import Flow
from flowno.core.node_base import (
    DraftInputPortRef,
    DraftNode,
    FinalizedNode,
    NodePlaceholder,
    OutputPortRefPlaceholder,
)
from typing_extensions import Self, TypeVarTuple, Unpack, override
from collections import OrderedDict

logger = logging.getLogger(__name__)

_Ts = TypeVarTuple("_Ts")
_ReturnTupleT_co = TypeVar("_ReturnTupleT_co", covariant=True, bound=tuple[object, ...])

class FlowHDLView:
    """Base implementation of the :class:`FlowHDL` attribute protocol.

    ``FlowHDLView`` acts like a simple namespace for draft nodes.  Public
    attribute assignments are stored in ``self._nodes`` while private names
    (those starting with ``_``) behave like normal Python attributes.  Accessing
    an undefined public attribute before the view is finalized returns a
    :class:`~flowno.core.node_base.NodePlaceholder` so that connections can be
    declared before the target node is defined.  Once finalized, attribute
    lookups behave normally and missing attributes raise :class:`AttributeError`.
    """

    _is_finalized: bool
    _flow: Flow
    
    KEYWORDS: ClassVar[list[str]] = []

    contextStack: ClassVar[OrderedDict[Self, list[DraftNode]]] = OrderedDict()

    def __init__(self) -> None:
        self._is_finalized = False
        self._nodes: dict[str, Any] = {}  # pyright: ignore[reportExplicitAny]

    def __enter__(self: Self) -> Self:
        """Enter the context by adding this instance to the context stack."""
        self.__class__.contextStack[self] = []
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Finalize the graph when exiting the context by calling :meth:`_finalize`."""
        self.__class__.contextStack.popitem()
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

    @classmethod
    def register_node(cls, node: DraftNode[Unpack[_Ts], _ReturnTupleT_co]) -> None:
        """Register a draft node in the context stack."""
        if cls.contextStack:
            # Get the last FlowHDL instance in the context stack
            last_hdl = next(reversed(cls.contextStack))
            cls.contextStack[last_hdl].append(node)
        else:
            raise RuntimeError("No FlowHDL context is active to register the node.")
    
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
