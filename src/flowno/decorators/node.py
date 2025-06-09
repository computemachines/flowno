"""
Node decorator for Flowno.

This module provides the `@node` decorator, which transforms async functions or classes
into DraftNode subclasses. These nodes can then be used within a FlowHDL context to
define dataflow graphs.

Examples:
    Basic usage:
    
    >>> from flowno import node
    >>> 
    >>> @node
    ... async def Add(x: int, y: int) -> int:
    ...     return x + y
    >>> 
    >>> add_node = Add(1, 2)
    >>> print(add_node)  # DraftNode instance

    With stream inputs:
    
    >>> from flowno import node, Stream
    >>> 
    >>> @node(stream_in=["a"])
    ... async def SumStream(x: int, a: Stream[int]) -> int:
    ...     total = x
    ...     async for value in a:
    ...         total += value
    ...     return total
    >>> 
    >>> sum_stream_node = SumStream(1)
    >>> print(sum_stream_node)  # DraftNode instance with stream input

    With multiple outputs:
    
    >>> from flowno import node
    >>> 
    >>> @node(multiple_outputs=True)
    ... async def SumAndDiff(x: int, y: int) -> tuple[int, int]:
    ...     return x + y, x - y
    >>> 
    >>> sum_and_diff_node = SumAndDiff(3, 1)
    >>> print(sum_and_diff_node)  # DraftNode instance with multiple outputs
"""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing_extensions import Unpack
from typing import Any, Final, Literal, TypeVar, Union, overload, ClassVar
import logging

logger = logging.getLogger(__name__)

from flowno.core.mono_node import (
    MonoNode,
    MonoNode0,
    MonoNode0_0,
    MonoNode0_1,
    MonoNode1,
    MonoNode2,
)
from flowno.core.node_base import DraftNode, OriginalCall
from flowno.core.streaming_node import (
    StreamingNode,
    StreamingNode0,
    StreamingNode1,
    StreamingNode2,
)
from flowno.decorators.node_meta_multiple_dec import node_meta_multiple_dec
from flowno.decorators.node_meta_single_dec import node_meta_single_dec
from flowno.decorators.single_output import (
    ClassCall,
    MonoClassCall,
    StreamingClassCall,
    create_class_node_subclass_single,
    create_func_node_factory_single,
)
from typing_extensions import override

EMPTY_LIST: Final[list[str]] = []  # used to make the typing happy

_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")
_ReturnT = TypeVar("_ReturnT")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
_ReturnT_co = TypeVar("_ReturnT_co", covariant=True)
_ReturnTupleT_co = TypeVar("_ReturnTupleT_co", bound=tuple[object, ...], covariant=True)

# # Eg:
# # @node
# # class StatefulNode:
# #     async def call(self, x: str, y: int) -> int:
# @overload
# def node(
#     func_or_cls: type[BlockingClassCall[T1, T2, _ReturnT_co]], /
# ) -> type[MonoNode2[T1, T2, tuple[_ReturnT_co]]]: ...


# # Eg:
# # @node
# # class StatefulNode:
# #     async def call(self, x: str, y: int) -> AsyncGenerator[int, None]:
# @overload
# def node(
#     func_or_cls: type[StreamingClassCall[T1, T2, _ReturnT_co]], /
# ) -> type[StreamingNode2[T1, T2, tuple[_ReturnT_co]]
# ]: ...


# # Eg:
# # @node
# # class StatefulNode:
# #     async def call(self, x: str) -> int:
# @overload
# def node(
#     func_or_cls: type[BlockingClassCall[T1, _ReturnT_co]], /
# ) -> type[MonoNode1[T1, tuple[_ReturnT_co]]]: ...


# # Eg:
# # @node
# # class StatefulNode:
# #     async def call(self, x: str) -> AsyncGenerator[int, None]:
# @overload
# def node(
#     func_or_cls: type[StreamingClassCall[T1, _ReturnT_co]], /
# ) -> type[StreamingNode1[T1, tuple[_ReturnT_co]]]: ...


# # Eg:
# # @node
# # class StatefulNode:
# #     async def call(self) -> int:
# @overload
# def node(
#     func_or_cls: type[MonoClassCall[_ReturnT_co]], /
# ) -> type[MonoNode0[tuple[_ReturnT_co]]]: ...


# # Eg:
# # @node
# # class StatefulNode:
# #     async def call(self) -> AsyncGenerator[int, None]:
# @overload
# def node(
#     func_or_cls: type[StreamingClassCall[_ReturnT_co]], /
# ) -> type[StreamingNode0[tuple[_ReturnT_co]]]: ...


# # Eg:
# # @node
# # async def StatelessNode(x: str, y: int) -> int:
# @overload
# def node(
#     func_or_cls: Callable[[T1, T2], Coroutine[Any, Any, _ReturnT_co]], /
# ) -> type[MonoNode2[T1, T2, tuple[_ReturnT_co]]
# ]: ...


# # Eg:
# # @node
# # async def StatelessNode(x: str, y: int) -> AsyncGenerator[int, None]:
# @overload
# def node(
#     func_or_cls: Callable[[T1, T2], AsyncGenerator[_ReturnT_co, None]], /
# ) -> type[StreamingNode2[T1, T2, tuple[_ReturnT_co]]
# ]: ...


# Eg:
# @node
# async def StatelessNode(x: str) -> int:
@overload
def node(
    func_or_cls: Callable[[T1], Coroutine[Any, Any, _ReturnT_co]], /
) -> type[MonoNode1[T1, tuple[_ReturnT_co]]]: ...


# # Eg:
# # @node
# # async def StatelessNode(x: str) -> AsyncGenerator[int, None]:
# @overload
# def node(
#     func_or_cls: Callable[[T1], AsyncGenerator[_ReturnT_co, None]], /
# ) -> type[StreamingNode1[T1, tuple[_ReturnT_co]]
# ]: ...


# Eg:
# @node
# async def StatelessNode() -> int:
@overload
def node(func_or_cls: Callable[[], Coroutine[Any, Any, None]], /) -> type[MonoNode0_0]: ...


@overload
def node(func_or_cls: Callable[[], Coroutine[Any, Any, _ReturnT_co]], /) -> type[MonoNode0_1[_ReturnT_co]]: ...


# # Eg:
# # @node
# # async def StatelessNode() -> AsyncGenerator[int, None]:
# @overload
# def node(
#     func_or_cls: Callable[[], AsyncGenerator[_ReturnT_co, None]], /
# ) -> type[StreamingNode0[tuple[_ReturnT_co]]]: ...


# Eg:
# @node(stream_in=["a"])
# async def StatelessNode(x: str, a: Stream[int]) -> int:
# or:
# @node(stream_in=["a"])
# async def StatelessNode(x: str, a: Stream[int]) -> AsyncGenerator[int, None]:
@overload
def node(
    func_or_cls: None = None,
    /,
    *,
    multiple_outputs: Literal[False] | None = None,
    stream_in: list[str] = EMPTY_LIST,
) -> node_meta_single_dec: ...


# # Eg:
# # @node(stream_in=["a"], multiple_outputs=True)
# # async def StatelessNode(x: str, a: Stream[int]) -> tuple[int, int]:
# # or:
# # @node(stream_in=["a"], multiple_outputs=True)
# # async def StatelessNode(x: str, a: Stream[int]) -> AsyncGenerator[tuple[int, int], None]:
# @overload
# def node(
#     func_or_cls: None = None,
#     /,
#     *,
#     multiple_outputs: Literal[True],
#     stream_in: list[str] = EMPTY_LIST,
# ) -> node_meta_multiple_dec: ...


def node(
    func_or_cls: (
        Callable[..., Coroutine[Any, Any, _ReturnT_co]]
        | Callable[..., AsyncGenerator[_ReturnT_co, None]]
        | type[ClassCall[Any, _ReturnT_co]]
        | None
    ) = None,
    /,
    *,
    multiple_outputs: Literal[False] | Literal[True] | None = None,
    stream_in: list[str] = EMPTY_LIST,
) -> (
    type[MonoNode[Unpack[tuple[Any, ...]], tuple[_ReturnT_co]]]
    | type[StreamingNode[Unpack[tuple[Any, ...]], tuple[_ReturnT_co]]]
    | node_meta_single_dec
    | node_meta_multiple_dec[Unpack[tuple[object, ...]], _ReturnTupleT_co]
):
    """
    Decorator that transforms async functions or classes into DraftNode subclasses.

    Args:
        func_or_cls: The async function or class to transform
        multiple_outputs: Whether the node has multiple outputs
        stream_in: List of input streams

    Returns:
        A DraftNode subclass or a node_meta decorator

    Examples:
        Basic usage:
        
        >>> from flowno import node
        >>> 
        >>> @node
        ... async def Add(x: int, y: int) -> int:
        ...     return x + y
        >>> 
        >>> add_node = Add(1, 2)
        >>> print(add_node)  # DraftNode instance

        With stream inputs:
        
        >>> from flowno import node, Stream
        >>> 
        >>> @node(stream_in=["a"])
        ... async def SumStream(x: int, a: Stream[int]) -> int:
        ...     total = x
        ...     async for value in a:
        ...         total += value
        ...     return total
        >>> 
        >>> sum_stream_node = SumStream(1)
        >>> print(sum_stream_node)  # DraftNode instance with stream input

        With multiple outputs:
        
        >>> from flowno import node
        >>> 
        >>> @node(multiple_outputs=True)
        ... async def SumAndDiff(x: int, y: int) -> tuple[int, int]:
        ...     return x + y, x - y
        >>> 
        >>> sum_and_diff_node = SumAndDiff(3, 1)
        >>> print(sum_and_diff_node)  # DraftNode instance with multiple outputs
    """
    if func_or_cls is not None:
        # both stream_in and multiple_outputs are unset
        if isinstance(func_or_cls, type):
            return create_class_node_subclass_single(func_or_cls, stream_in)
        else:
            return create_func_node_factory_single(func_or_cls, stream_in)
    elif multiple_outputs is not True:
        return node_meta_single_dec(stream_in=stream_in)
    else:
        return node_meta_multiple_dec(stream_in=stream_in)
from inspect import signature, Parameter
from flowno.core.group_node import DraftGroupNode


def create_func_group_node_subclass(func: Callable[..., DraftNode]) -> type[DraftGroupNode]:
    logger.debug(f"define template group {func.__name__}")
    func_sig = signature(func)
    params = list(func_sig.parameters.values())[1:]  # drop FlowHDLView parameter
    default_values: dict[int, object] = {}
    for idx, p in enumerate(params):
        if p.default is not Parameter.empty:
            default_values[idx] = p.default

    class DynamicGroupNode(DraftGroupNode):
        _minimum_run_level: ClassVar[list[int]] = []
        _default_values: ClassVar[dict[int, object]] = default_values
        _original_call = OriginalCall(
            call_signature=func_sig,
            call_code=func.__code__,
            func_name=func.__name__,
            class_name=None,
        )
        original_func = staticmethod(func)

    DynamicGroupNode.__name__ = func.__name__
    return DynamicGroupNode


def template(func: Callable[..., DraftNode]) -> type[DraftGroupNode]:
    return create_func_group_node_subclass(func)


# expose attribute so users can write @node.template
node.template = template
