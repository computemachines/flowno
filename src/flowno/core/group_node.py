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

    @override
    def __init__(self, *args: Unpack[tuple[Any, ...]]):
        logger.debug(f"instantiate group {self.__class__.__name__}")
        super().__init__(*args)
        from .flow_hdl_view import FlowHDLView

        closest_context = next(reversed(FlowHDLView.contextStack))
        if closest_context is None:
            raise RuntimeError("A group node must be defined within a FlowHDL context")

        with FlowHDLView(
            on_register_finalized_node=closest_context._on_register_finalized_node
        ) as sub_view:
            self._return_node = self.__class__.original_func(sub_view, *args)
            self._debug_context_nodes = FlowHDLView.contextStack[sub_view]

    async def call(self, *args: Unpack[_Ts]):  # type: ignore[override]
        raise RuntimeError("Group nodes do not run")

    def debug_dummy(self) -> None:
        logger.debug(
            f"finalize group {self.__class__.__name__} with sub nodes {self._debug_context_nodes} and return node {self._return_node}"
        )
