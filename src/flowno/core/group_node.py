import logging
from typing import Any, ClassVar, TYPE_CHECKING

from typing_extensions import TypeVarTuple, Unpack, override

from .node_base import DraftNode, OriginalCall

if TYPE_CHECKING:
    from .flow_hdl_view import FlowHDLView

logger = logging.getLogger(__name__)

_Ts = TypeVarTuple("_Ts")
_ReturnTupleT_co = tuple[Any, ...]


class DraftGroupNode(DraftNode[Unpack[_Ts], tuple[Any, ...]]):
    """Minimal draft group node used for experimenting with template groups."""

    original_func: ClassVar[Any]
    _return_node: DraftNode
    _capture_nodes: ClassVar[list[DraftNode]] = []

    @override
    def __init__(self, *args: Unpack[tuple[Any, ...]]):
        logger.debug(f"instantiate group {self.__class__.__name__}")
        super().__init__(*args)
        from .flow_hdl_view import FlowHDLView

        closest_context = next(reversed(FlowHDLView.contextStack))
        if closest_context is None:
            raise RuntimeError("A group node must be defined within a FlowHDL context")

        captured = list(self.__class__._capture_nodes)
        for n in captured:
            try:
                FlowHDLView.contextStack[closest_context].remove(n)
            except (KeyError, ValueError):
                pass

        with FlowHDLView(
            on_register_finalized_node=closest_context._on_register_finalized_node
        ) as sub_view:
            FlowHDLView.contextStack[sub_view].extend(captured)
            self._return_node = self.__class__.original_func(sub_view, *args)
            self._debug_context_nodes = FlowHDLView.contextStack[sub_view]
        
    async def call(self, *args: Unpack[_Ts]):  # type: ignore[override]
        raise RuntimeError("Group nodes do not run")

    def debug_dummy(self) -> None:
        logger.debug(
            f"finalize group {self.__class__.__name__} with sub nodes {self._debug_context_nodes} and return node {self._return_node}"
        )

    def if_(self, predicate: object) -> "DraftGroupNode":
        """Wrap this group with a :class:`PropagateIf` node.

        The conditional node is inserted *after* the group's return node so the
        entire group executes but its output is gated by ``predicate``. Any
        existing consumers of this group are rewired to consume the conditional
        output.
        """

        from .flow_hdl_view import FlowHDLView
        from flowno.decorators import node
        from .node_base import DraftInputPortRef, DraftOutputPortRef
        from .types import InputPortIndex, OutputPortIndex
        from .node_base import PropagateIf

        # Capture existing downstream connections so they can be rewired to the
        # conditional group after creation.
        downstream: list[tuple[DraftNode, InputPortIndex]] = []
        for out_idx, consumers in list(self._connected_output_nodes.items()):
            for consumer in list(consumers):
                for in_idx, port in consumer._input_ports.items():
                    conn = port.connected_output
                    if (
                        isinstance(conn, DraftOutputPortRef)
                        and conn.node is self
                        and conn.port_index == OutputPortIndex(out_idx)
                    ):
                        downstream.append((consumer, InputPortIndex(in_idx)))
                        try:
                            self._connected_output_nodes[OutputPortIndex(out_idx)].remove(consumer)
                        except (KeyError, ValueError):
                            pass
                        port.connected_output = None

        @node.template(capture=[self])
        def _IfGroup(f: FlowHDLView, pred: object) -> DraftNode:
            return PropagateIf(pred, self)

        if FlowHDLView.contextStack:
            ctx = next(reversed(FlowHDLView.contextStack))
            try:
                FlowHDLView.contextStack[ctx].remove(self)
            except ValueError:
                pass

        conditional_group = _IfGroup(predicate)

        # Reconnect previous consumers to the conditional group's output
        for consumer, idx in downstream:
            conditional_group.output(0).connect(DraftInputPortRef(consumer, idx))

        return conditional_group
