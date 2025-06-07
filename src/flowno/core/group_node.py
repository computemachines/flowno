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
    _sub_view: 'FlowHDLView'
    _return_node: DraftNode

    @override
    def __init__(self, *args: Unpack[tuple[Any, ...]]):
        print(f"[DEBUG] instantiate group {self.__class__.__name__}")
        super().__init__(*args)
        from .flow_hdl_view import FlowHDLView

        parent = next(reversed(FlowHDLView.contextStack))
        with FlowHDLView() as sub_view:
            sub_view._flow = getattr(parent, "_flow", None)  # type: ignore[attr-defined]
            self._return_node = self.__class__.original_func(sub_view, *args)
        self._sub_view = sub_view

    async def call(self, *args: Unpack[_Ts]):  # type: ignore[override]
        raise RuntimeError("Group nodes do not run")

    def debug_dummy(self) -> None:
        print(
            f"[DEBUG] finalize group {self.__class__.__name__} with sub nodes {list(self._sub_view._nodes.keys())}"
        )
