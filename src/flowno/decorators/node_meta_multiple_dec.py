"""
Node meta decoration for multiple-output Flowno nodes.

This module provides the `node_meta_multiple_dec` class, which handles the decorator
logic for multiple-output node cases in the Flowno framework:
- @node(multiple_outputs=True)
- @node(multiple_outputs=True, stream_in=[...])

This is an internal implementation detail used by the :py:mod:`flowno.decorators.node`
decorator, not meant to be used directly. See the node decorator documentation for
complete usage information and examples.
"""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, Final, TypeVar
from typing_extensions import overload
from typing import Generic
from typing_extensions import TypeVarTuple, Unpack
from flowno.core.mono_node import (
    MonoNode,
    MonoNode0,
    MonoNode1,
    MonoNode2,
)
from flowno.core.node_base import DraftNode
from flowno.core.streaming_node import (
    StreamingNode,
    StreamingNode0,
    StreamingNode1,
    StreamingNode2,
)
from flowno.decorators.multiple_output import create_func_node_factory_multiple

EMPTY_LIST: Final[list[str]] = []

_T1 = TypeVar("_T1")
_ReturnTupleT_co = TypeVar("_ReturnTupleT_co", covariant=True, bound=tuple[object, ...])
_T2 = TypeVar("_T2")
Ts = TypeVarTuple("Ts")

class node_meta_multiple_dec(Generic[Unpack[Ts], _ReturnTupleT_co]):
    """
    Handles the decorator logic for multiple-output cases:
        - @node(multiple_outputs=True)
        - @node(multiple_outputs=True, stream_in=...)
    
    This class is returned by the @node() function when called with multiple_outputs=True,
    and implements __call__ to handle the actual function decoration. It creates
    appropriate DraftNode subclasses based on the decorated function and specified parameters.
    
    Args:
        stream_in: List of parameter names that should be treated as streaming inputs
    
    Returns:
        When called with a function, returns a DraftNode subclass factory for that function
        that preserves the tuple structure of multiple return values
    """

    def __init__(self, stream_in: list[str] = EMPTY_LIST) -> None:
        self.stream_in: list[str] = stream_in

    # @overload
    # def __call__(self, func: Callable[[_T1, _T2], Coroutine[Any, Any, _ReturnTupleT_co]]) -> type[
    #     MonoNode2[_T1, _T2, _ReturnTupleT_co]
    # ]: ...

    # @overload
    # def __call__(self, func: Callable[[_T1, _T2], AsyncGenerator[_ReturnTupleT_co, None]]) -> type[
    #     StreamingNode2[_T1, _T2, _ReturnTupleT_co]
    # ]: ...

    # @overload
    # def __call__(self, func: Callable[[_T1], Coroutine[Any, Any, _ReturnTupleT_co]]) -> type[
    #     MonoNode1[_T1, _ReturnTupleT_co]
    # ]: ...

    # @overload
    # def __call__(self, func: Callable[[_T1], AsyncGenerator[_ReturnTupleT_co, None]]) -> type[
    #     StreamingNode1[_T1, _ReturnTupleT_co]
    # ]: ...

    # @overload
    # def __call__(self, func: Callable[[], Coroutine[Any, Any, _ReturnTupleT_co]]) -> type[
    #     MonoNode0[_ReturnTupleT_co]
    # ]: ...

    # @overload
    # def __call__(self, func: Callable[[], AsyncGenerator[_ReturnTupleT_co, None]]) -> type[
    #     StreamingNode0[_ReturnTupleT_co]
    # ]: ...

    # @overload
    # def __call__(self, func: Callable[[Unpack[Ts]], Coroutine[Any, Any, _ReturnTupleT_co]]) -> type[
    #     MonoNode[Unpack[Ts], _ReturnTupleT_co]
    # ]: ...

    # @overload
    # def __call__(self, func: Callable[[Unpack[Ts]], AsyncGenerator[_ReturnTupleT_co, None]]) -> type[
    #     StreamingNode[Unpack[Ts], _ReturnTupleT_co]
    # ]: ...

    def __call__(
        self,
        func: (
            Callable[[Unpack[Ts]], Coroutine[Any, Any, _ReturnTupleT_co]]
            | Callable[[Unpack[Ts]], AsyncGenerator[_ReturnTupleT_co, None]]
        ),
    ) -> type[DraftNode[Unpack[Ts], _ReturnTupleT_co]]:  # type: ignore[type-var]
        """
        Apply the decorator to the given function.
        
        This method is called when the decorator is applied to a function.
        It delegates to create_func_node_factory_multiple to create a DraftNode
        subclass that preserves the tuple structure of multiple return values.
        
        Args:
            func: The function to transform into a node
            
        Returns:
            A DraftNode subclass factory for the decorated function
        """
        return create_func_node_factory_multiple(func, self.stream_in)
