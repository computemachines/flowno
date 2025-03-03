"""
Node meta decoration for single-output Flowno nodes.

This module provides the `node_meta_single_dec` class, which handles the decorator
logic for single-output node cases in the Flowno framework:
- @node()
- @node(multiple_outputs=False) 
- @node(stream_in=[...])

This is an internal implementation detail used by the :py:mod:`flowno.decorators.node`
decorator, not meant to be used directly. See the node decorator documentation for
complete usage information and examples.
"""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Final, Generic, TypeVar, overload
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
from flowno.decorators.single_output import (
    MonoClassCall,
    ClassCall,
    StreamingClassCall,
    create_class_node_subclass_single,
    create_func_node_factory_single,
)

EMPTY_LIST: Final[list[str]] = []  # used to make the typing happy

# Define type variables
T1 = TypeVar('T1')
T2 = TypeVar('T2')
_ReturnT_co = TypeVar('_ReturnT_co', covariant=True)
Ts = TypeVarTuple('Ts')


class node_meta_single_dec:
    """
    Handles the decorator logic for single-output node cases.
    
    This class is returned by the @node() function when called with parameters,
    and implements __call__ to handle the actual function decoration. It creates
    appropriate DraftNode subclasses based on the decorated function or class
    and specified parameters.
    
    Args:
        stream_in: List of parameter names that should be treated as streaming inputs
    
    Returns:
        When called with a function or class, returns a DraftNode subclass
        factory for that function or class
    """

    def __init__(self, stream_in: list[str] = EMPTY_LIST) -> None:
        self.stream_in: list[str] = stream_in

    # @overload
    # def __call__(
    #     self, func_or_cls: type[BlockingClassCall[T1, T2, _ReturnT_co]], /
    # ) -> type[MonoNode2[T1, T2, tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: type[StreamingClassCall[T1, T2, _ReturnT_co]], /
    # ) -> type[StreamingNode2[T1, T2, tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: type[BlockingClassCall[T1, _ReturnT_co]], /
    # ) -> type[MonoNode1[T1, tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: type[StreamingClassCall[T1, _ReturnT_co]], /
    # ) -> type[StreamingNode1[T1, tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: type[BlockingClassCall[_ReturnT_co]], /
    # ) -> type[MonoNode0[tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: type[StreamingClassCall[_ReturnT_co]], /
    # ) -> type[StreamingNode0[tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: Callable[[T1, T2], Coroutine[object, object, _ReturnT_co]]
    # ) -> type[MonoNode2[T1, T2, tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: Callable[[T1, T2], AsyncGenerator[_ReturnT_co, None]]
    # ) -> type[StreamingNode2[T1, T2, tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: Callable[[T1], Coroutine[object, object, _ReturnT_co]]
    # ) -> type[MonoNode1[T1, tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: Callable[[T1], AsyncGenerator[_ReturnT_co, None]]
    # ) -> type[StreamingNode1[T1, tuple[_ReturnT_co]]]: ...

    @overload
    def __call__(
        self, func_or_cls: Callable[[], Coroutine[object, object, _ReturnT_co]]
    ) -> type[MonoNode0[tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self, func_or_cls: Callable[[], AsyncGenerator[_ReturnT_co, None]]
    # ) -> type[StreamingNode0[tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self,
    #     func_or_cls: Callable[[Unpack[Ts]], Coroutine[object, object, _ReturnT_co]]
    # ) -> type[MonoNode[Unpack[Ts], tuple[_ReturnT_co]]]: ...

    # @overload
    # def __call__(
    #     self,
    #     func_or_cls: Callable[[Unpack[Ts]], AsyncGenerator[_ReturnT_co, None]]
    # ) -> type[StreamingNode[Unpack[Ts], tuple[_ReturnT_co]]]: ...

    def __call__(
        self,
        func_or_cls: (
            Callable[[Unpack[Ts]], Coroutine[object, object, _ReturnT_co]]
            | Callable[[Unpack[Ts]], AsyncGenerator[_ReturnT_co, None]]
            | type[ClassCall[Unpack[Ts], _ReturnT_co]]
        ),
    ) -> type[DraftNode[Unpack[Ts], tuple[_ReturnT_co]]]:
        """
        Apply the decorator to the given function or class.
        
        This method is called when the decorator is applied to a function or class.
        It delegates to either create_class_node_subclass_single or 
        create_func_node_factory_single depending on whether the decorated object
        is a class or function.
        
        Args:
            func_or_cls: The function or class to transform into a node
            
        Returns:
            A DraftNode subclass factory for the decorated function or class
        """
        if isinstance(func_or_cls, type):
            return create_class_node_subclass_single(func_or_cls, self.stream_in)
        else:
            return create_func_node_factory_single(func_or_cls, self.stream_in)
