"""
Type definitions for mono nodes in Flowno's typechecking system.

A *Mono Node* is a node that returns a single value or tuple via return statement
rather than streaming values via yield. This module defines Protocol classes
that improve typechecking specificity for different node arities.

Examples:
    >>> @node
    ... def Add(a: int, b: int) -> int:
    ...     return a + b

    >>> @node(multiple_outputs=True)
    ... def SumAndDiff(a: int, b: int):
    ...     return a + b, a - b

.. warning::

    These classes are *never* instantiated directly - they exist solely for
    static type checking.

.. admonition:: Naming Conventions

    - MonoNode: Base protocol for all mono nodes regardless of arity
    - MonoNodeX: Node with X inputs and any number of outputs
    - MonoNodeX_Y: Node with X inputs and Y outputs

.. seealso::

    - :mod:`flowno.core.streaming_node`: Type definitions for streaming nodes
"""

from abc import abstractmethod
from collections.abc import Coroutine
from types import NotImplementedType
from typing import Any, Literal, Protocol, TypeAlias, TypeVar, overload

from flowno.core.node_base import DraftNode, DraftOutputPortRef
from typing_extensions import TypeVarTuple, Unpack, override

_ReturnTupleT_co = TypeVar("_ReturnTupleT_co", covariant=True, bound=tuple[object, ...])
"""Type variable for the return type of a mono node."""

_T1_contra = TypeVar("_T1_contra", contravariant=True)
_T2_contra = TypeVar("_T2_contra", contravariant=True)
Ts = TypeVarTuple("Ts")
"""Type variable for the input types of a mono node."""

_Tout = TypeVar("_Tout", covariant=True)
_T1_co = TypeVar("_T1_co", covariant=True)
_T2_co = TypeVar("_T2_co", covariant=True)


class MonoDraftOutputPortRef(DraftOutputPortRef[_Tout]):
    pass


class MonoNode(Protocol[Unpack[Ts], _ReturnTupleT_co]):
    """Protocol for mono nodes that produce a single tuple return value.

    A mono node is a node that returns a single value or tuple rather than
    streaming values via yield statements. This class serves as the base
    Protocol for all mono node arities.

    Note: This class is never instantiated - it exists solely for typechecking.
    """

    def __init__(self, *args: Unpack[tuple[Any, ...]]): ...
    def call(self, *args: Unpack[Ts]) -> Coroutine[Any, Any, _ReturnTupleT_co]: ...


class MonoNode0(DraftNode[_ReturnTupleT_co]):
    """A mono node with 0 inputs that returns a tuple.

    See MonoNode for details on the mono node protocol.
    """

    @abstractmethod
    def __init__(self): ...
    def call(self) -> Coroutine[Any, Any, _ReturnTupleT_co]: ...


class MonoNode0_0(MonoNode0[tuple[None]]):
    """A mono node with 0 inputs and 0 outputs.

    See MonoNode for details on the mono node protocol.
    """

    @abstractmethod
    def __init__(self): ...
    def call(self) -> Coroutine[Any, Any, tuple[None]]: ...

    @override
    def output(self, output_port: int) -> "NotImplementedType": ...


class MonoNode0_1(MonoNode0[tuple[_T1_co]]):
    """A mono node with 0 inputs and 1 output.

    See MonoNode for details on the mono node protocol.
    """

    @abstractmethod
    def __init__(self): ...
    def call(self) -> Coroutine[Any, Any, tuple[_T1_co]]: ...

    @overload
    def output(self, output_port: Literal[0]) -> "MonoDraftOutputPortRef[_T1_co]": ...

    @overload
    def output(self, output_port: int) -> "NotImplementedType": ...


_T1_co = TypeVar("_T1_co", covariant=True)
MonoNode_1: TypeAlias = DraftNode[Unpack[tuple[Any, ...]], tuple[_T1_co]]


class MonoNode1(
    DraftNode[_T1_contra, _ReturnTupleT_co],
):
    """A mono node with 1 input that returns a tuple.

    See MonoNode for details on the mono node protocol.
    """

    # Python 3.10 does not allow Unpack in an *args list
    @abstractmethod
    def __init__(self, *args: Any): ...  # TODO: Replace this with specific options when migrating to Python 3.11

    def call(self, arg1: _T1_contra) -> Coroutine[Any, Any, _ReturnTupleT_co]: ...


class MonoNode2(
    DraftNode[_T1_contra, _T2_contra, _ReturnTupleT_co],
):
    """A mono node with 2 inputs that returns a tuple.

    See MonoNode for details on the mono node protocol.
    """

    @abstractmethod
    def __init__(self): ...
    def call(self, arg1: _T1_contra, arg2: _T2_contra) -> Coroutine[Any, Any, _ReturnTupleT_co]: ...
