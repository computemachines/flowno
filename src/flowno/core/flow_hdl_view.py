from collections.abc import Callable
import inspect
import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ClassVar, TypeVar, cast

from flowno.core.flow.flow import Flow
from flowno.core.node_base import (
    DraftInputPortRef,
    DraftNode,
    DraftOutputPortRef,
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

    KEYWORDS: ClassVar[list[str]] = ["register_child_result"]

    contextStack: ClassVar[OrderedDict[Self, list[DraftNode]]] = OrderedDict()

    @dataclass
    class FinalizationResult:
        nodes: dict[str, Any]
        finalized_nodes: dict[
            DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]],
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ]

    def __init__(self, on_register_finalized_node: Callable[[FinalizedNode], None]) -> None:
        self._is_finalized = False
        self._nodes: dict[str, Any] = {}  # pyright: ignore[reportExplicitAny]
        self._child_results: list[FlowHDLView.FinalizationResult] = []
        self._on_register_finalized_node = on_register_finalized_node

    def __enter__(self: Self) -> Self:
        """Enter the context by adding this instance to the context stack."""
        self.__class__.contextStack[self] = []
        self._child_results = []
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Finalize the graph when exiting the context by calling :meth:`_finalize`."""
        _, draft_nodes = self.__class__.contextStack.popitem()
        finalize_connections = len(self.__class__.contextStack) == 0
        result = self._finalize(draft_nodes, finalize_connections=finalize_connections)
        if self.__class__.contextStack:
            parent = next(reversed(self.__class__.contextStack))
            parent.register_child_result(result)
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

    def register_child_result(self, result: "FlowHDLView.FinalizationResult") -> None:
        """Register a finalized child context result with this view."""
        self._child_results.append(result)

    def _finalize(self, draft_nodes: list[DraftNode], *, finalize_connections: bool = True) -> "FlowHDLView.FinalizationResult":
        """Finalize all the draft nodes instantiated in the FlowHDL context.

        Replace nodes defined in the FlowHDL context with their finalized
        counterparts, resolving all `OutputPortRefPlaceholder` instances to
        actual `DraftOutputPortRefs`.

        Args:
            draft_nodes (list[DraftNode]): A list of draft nodes that were created
                within this "layer" of the FlowHDL context.
        """
        logger.info("Finalizing FlowHDL")

        all_draft_nodes: list[DraftNode] = []
        finalized_nodes: dict[
            DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]],
            FinalizedNode[Unpack[tuple[object, ...]], tuple[object, ...]],
        ] = dict()

        for child in self._child_results:
            self._nodes.update(child.nodes)
            finalized_nodes.update(child.finalized_nodes)
            all_draft_nodes.extend(child.finalized_nodes.keys())

        # Map DraftGroupNodes to the draft node returned from the template.
        group_alias: dict[DraftGroupNode, DraftNode] = {}

        def resolve_target(node: DraftNode) -> DraftNode:
            while isinstance(node, DraftGroupNode):
                if node in group_alias:
                    node = group_alias[node]
                else:
                    node = node._return_node
            return node

        # Replace any DraftGroupNode references stored on this view with the
        # node that the group returned. These returned nodes are already part of
        # ``child.finalized_nodes`` and will be finalized alongside all other
        # draft nodes.
        for name, obj in list(self._nodes.items()):
            if isinstance(obj, DraftGroupNode):
                # Emit debug information when we first encounter the group node.
                obj.debug_dummy()
                target = resolve_target(obj._return_node)
                group_alias[obj] = target
                self._nodes[name] = target

        clean_draft_nodes: list[DraftNode] = []
        for dn in draft_nodes:
            if isinstance(dn, DraftGroupNode):
                # Avoid printing debug info twice if the group was stored on
                # this view and processed above.
                if dn not in group_alias:
                    dn.debug_dummy()
                target = resolve_target(dn._return_node)
                group_alias.setdefault(dn, target)
                continue
            all_draft_nodes.append(dn)
            clean_draft_nodes.append(dn)

        # Redirect any connections that target a DraftGroupNode to the draft
        # node produced by the group.  The group node itself is dropped from the
        # graph so upstream and downstream links must be rewired.
        for draft_node in all_draft_nodes:
            for input_port in draft_node._input_ports.values():
                conn = input_port.connected_output
                if (
                    isinstance(conn, DraftOutputPortRef)
                    and isinstance(conn.node, DraftGroupNode)
                    and conn.node in group_alias
                ):
                    group_node = conn.node
                    replacement = group_alias[group_node]
                    while isinstance(replacement, DraftGroupNode) and replacement in group_alias:
                        replacement = group_alias[replacement]
                    # Remove consumer from the group node
                    try:
                        group_node._connected_output_nodes[conn.port_index].remove(
                            draft_node
                        )
                    except (KeyError, ValueError):
                        pass
                    # Register consumer on the replacement node
                    replacement._connected_output_nodes[conn.port_index].append(
                        draft_node
                    )
                    conn.node = replacement

        # Also ensure producers no longer list the dropped group nodes. We
        # already added the replacement node as a consumer when we rewired the
        # input ports above, so simply drop the group node entries here.
        for producer in all_draft_nodes:
            for port_index, consumers in producer._connected_output_nodes.items():
                producer._connected_output_nodes[port_index] = [
                    c
                    for c in consumers
                    if not isinstance(c, DraftGroupNode)
                ]

        # ======== Phase 1 ========
        # Replace all OutputPortRefPlaceholders with actual DraftOutputPortRefs
        # OutputPortRefPlaceholders are generated when using a forward reference
        # on the FlowHDLView context.

        for unknown_node in all_draft_nodes:
            draft_node = cast(
                DraftNode[Unpack[tuple[object, ...]], tuple[object, ...]], unknown_node
            )

            # DraftInputPorts can have OutputPortRefPlaceholders or DraftOutputPortRefs
            # Step 1) Replace placholders with drafts
            for input_port_index, input_port in draft_node._input_ports.items():
                if input_port.connected_output is None:
                    if input_port.default_value != inspect.Parameter.empty:
                        logger.info(
                            f"{draft_node.input(input_port_index)} is not connected but has a default value"
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

        for draft_node in clean_draft_nodes:
            finalized_node = draft_node._blank_finalized()
            finalized_nodes[draft_node] = finalized_node
            self._on_register_finalized_node(finalized_node)

        if finalize_connections:
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
                    target = obj
                    while isinstance(target, DraftGroupNode) and target in group_alias:
                        target = group_alias[target]
                    self._nodes[name] = finalized_nodes[target]

            self._is_finalized = True
            self._child_results = []
            logger.debug("Finished Finalizing FlowHDL into Flow")

        return FlowHDLView.FinalizationResult(nodes=dict(self._nodes), finalized_nodes=finalized_nodes)
