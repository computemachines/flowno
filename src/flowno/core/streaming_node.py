"""
Type definitions for streaming nodes in Flowno's typechecking system.

A *Streaming Node* is a node that yields multiple values via async generator
rather than returning a single value or tuple. This module defines Protocol classes
that improve typechecking specificity for different node arities.

.. warning::

    These classes are *never* instantiated directly - they exist solely for
    static type checking.

.. admonition:: Naming Conventions

    - StreamingNode: Base protocol for all streaming nodes regardless of arity
    - StreamingNodeX: Node with X inputs that streams any number of outputs
    - StreamingNodeX_Y: Node with X inputs that streams Y outputs

.. seealso::

    - :mod:`flowno.core.mono_node`: Type definitions for mono nodes
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from types import NotImplementedType
from typing import Any, Literal, Protocol, TypeAlias, TypeVar, overload

from flowno.core.node_base import DraftNode, DraftOutputPortRef
from typing_extensions import TypeVarTuple, Unpack, override

_ReturnTupleT_co = TypeVar("_ReturnTupleT_co", covariant=True, bound=tuple[object, ...])
"""Type variable for the yielded tuple type of a streaming node."""

_T1_contra = TypeVar("_T1_contra", contravariant=True)
_T2_contra = TypeVar("_T2_contra", contravariant=True)
_Ts = TypeVarTuple("_Ts")
"""Type variable for the input types of a streaming node."""

_Tout = TypeVar("_Tout", covariant=True)
_T1_co = TypeVar("_T1_co", covariant=True)
_T2_co = TypeVar("_T2_co", covariant=True)


class StreamingDraftOutputPortRef(DraftOutputPortRef[_Tout]):
    pass


class StreamingNode(Protocol[Unpack[_Ts], _ReturnTupleT_co]):
    """Protocol for streaming nodes that produce async generators of tuples.

    A streaming node is a node that yields multiple values via async generator
    rather than returning a single value or tuple. This class serves as the base
    Protocol for all streaming node arities.

    Note: This class is never instantiated - it exists solely for typechecking.
    """

    def __init__(self, *args: Unpack[tuple[Any, ...]]): ...
    def call(self, *args: Unpack[_Ts]) -> AsyncGenerator[_ReturnTupleT_co, None]: ...


class StreamingNode0(DraftNode[_ReturnTupleT_co]):
    """A streaming node with 0 inputs that yields tuples.

    See StreamingNode for details on the streaming node protocol.
    """

    @abstractmethod
    def __init__(self): ...
    def call(self) -> AsyncGenerator[_ReturnTupleT_co, None]: ...


class StreamingNode0_0(StreamingNode0[tuple[None]], ABC):
    """A streaming node with 0 inputs and 0 outputs.

    See StreamingNode for details on the streaming node protocol.
    """

    @abstractmethod
    def __init__(self): ...

    @override
    def call(self) -> AsyncGenerator[tuple[None], None]: ...

    @override
    def output(self, output_port: int) -> "NotImplementedType": ...


class StreamingNode0_1(StreamingNode0[tuple[_T1_co]], ABC):
    """A streaming node with 0 inputs and 1 output.

    See StreamingNode for details on the streaming node protocol.
    """

    @abstractmethod
    def __init__(self): ...

    @override
    def call(self) -> AsyncGenerator[tuple[_T1_co], None]: ...

    @overload
    def output(self, output_port: Literal[0]) -> "StreamingDraftOutputPortRef[_T1_co]": ...

    @overload
    def output(self, output_port: int) -> "NotImplementedType | StreamingDraftOutputPortRef[_T1_co]": ...

    @override
    def output(self, output_port: int) -> "NotImplementedType | StreamingDraftOutputPortRef[_T1_co]": ...


_T1_co = TypeVar("_T1_co", covariant=True)
StreamingNode_1: TypeAlias = DraftNode[Unpack[tuple[Any, ...]], tuple[_T1_co]]


class StreamingNode1(
    DraftNode[_T1_contra, _ReturnTupleT_co],
):
    """A streaming node with 1 input that yields tuples.

    See StreamingNode for details on the streaming node protocol.
    """

    # Python 3.10 does not allow Unpack in an *args list
    @abstractmethod
    def __init__(self, *args: Any): ...  # TODO: Replace this with specific options when migrating to Python 3.11

    def call(self, arg1: _T1_contra) -> AsyncGenerator[_ReturnTupleT_co, None]: ...


class StreamingNode2(
    DraftNode[_T1_contra, _T2_contra, _ReturnTupleT_co],
):
    """A streaming node with 2 inputs that yields tuples.

    See StreamingNode for details on the streaming node protocol.
    """

    @abstractmethod
    def __init__(self): ...
    def call(self, arg1: _T1_contra, arg2: _T2_contra) -> AsyncGenerator[_ReturnTupleT_co, None]: ...
