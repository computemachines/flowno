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
from flowno.core.group_node import DraftGroupNode
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
        _, draft_nodes = self.__class__.contextStack.popitem()
        self._finalize(draft_nodes)
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
            # raise RuntimeError("No FlowHDL context is active to register the node.")
            logger.warning(
                f"Node, {node}, registered outside of FlowHDL context. "
                "This node will not be automatically finalized."
            )

    def _finalize(self, draft_nodes: list[DraftNode]) -> None:
        """Finalize all the draft nodes instantiated in the FlowHDL context.

        Replace nodes defined in the FlowHDL context with their finalized
        counterparts, resolving all `OutputPortRefPlaceholder` instances to
        actual `DraftOutputPortRefs`.

        Args:
            draft_nodes (list[DraftNode]): A list of draft nodes that were created
                within this "layer" of the FlowHDL context.
        """
        logger.info("Finalizing FlowHDL")

        for dn in draft_nodes:
            if isinstance(dn, DraftGroupNode):
                dn.debug_dummy()

        finalized_nodes: dict[
            DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]],
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ] = dict()

        # ======== Phase 1 ========
        # Replace all OutputPortRefPlaceholders with actual DraftOutputPortRefs
        # OutputPortRefPlaceholders are generated when using a forward reference
        # on the FlowHDLView context.

        for unknown_node in draft_nodes:
            draft_node = cast(
                DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], unknown_node
            )

            # DraftInputPorts can have OutputPortRefPlaceholders or DraftOutputPortRefs
            # Step 1) Replace placholders with drafts
            for input_port_index, input_port in draft_node._input_ports.items():
                if input_port.connected_output is None:
                    if input_port.default_value != inspect.Parameter.empty:
                        logger.info(
                            f"{draft_node.input(input_port_index)} is not connected and but has a default value"
                        )
                        continue
                    else:
                        # TODO: Use the same underlined format as supernode.py
                        raise AttributeError(
                            f"{draft_node.input(input_port_index)} is not connected and has no default value"
                        )

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
                                f"Cannot connect {draft_node} to non-DraftNode {connected_output.node.name}"
                            )
                        )

                    # the placeholder was defined on the FlowHDL instance and is a DraftNode, so connect the nodes
                    logger.debug(f"Connecting {output_source_node} to {input_port}")
                    output_source_node.output(
                        input_port.connected_output.port_index
                    ).connect(draft_node.input(input_port_index))

        # ======== Phase 2 ========
        # Now that all OutputPortRefPlaceholders have been replaced with
        # DraftOutputPortRefs, we wrap each draft node in a blank finalized node
        # and register it with the flow.

        for draft_node in draft_nodes:
            finalized_node = draft_node._blank_finalized()
            finalized_nodes[draft_node] = finalized_node
            self._flow.add_node(finalized_node)

        # ======== Phase 3 ========
        # Now that the finalized nodes exist, we can finalize wire up the connections.

        for draft_node, finalized_node in finalized_nodes.items():
            finalized_node._input_ports = {
                index: draft_input_port._finalize(index, finalized_nodes)
                for index, draft_input_port in draft_node._input_ports.items()
            }
            finalized_node._connected_output_nodes = {
                index: [
                    finalized_nodes[connected_draft]
                    for connected_draft in connected_drafts
                ]
                for index, connected_drafts in draft_node._connected_output_nodes.items()
            }

        # ======== Phase 4 ========
        # Replace all DraftNodes in self._nodes with their finalized counterparts.

        for name, obj in self._nodes.items():
            if isinstance(obj, DraftNode):
                self._nodes[name] = finalized_nodes[obj]

        self._is_finalized = True
        logger.debug("Finished Finalizing FlowHDL into Flow")
