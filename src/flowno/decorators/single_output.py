"""
Single output node creation utilities for Flowno.

This module provides utilities for creating single output nodes, which are used
internally by the :py:mod:`flowno.decorators.node` module. These utilities help
transform async functions or classes into DraftNode subclasses with single outputs.

For more information and examples, see the :py:mod:`flowno.decorators.node` module.
"""

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from inspect import Parameter, signature
from typing import Any, Protocol, Tuple, TypeVar, Union, cast

from flowno.core.mono_node import MonoNode
from flowno.core.node_base import DraftNode, OriginalCall
from flowno.core.streaming_node import StreamingNode
from flowno.core.types import RunLevel
from flowno.decorators.wrappers import wrap_async_generator_tuple, wrap_coroutine_tuple
from typing_extensions import TypeVarTuple, Unpack, override

logger = logging.getLogger(__name__)

T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")
_ReturnT_co = TypeVar("_ReturnT_co", covariant=True)
T1_inner = TypeVar("T1_inner")
_ReturnT_inner_co = TypeVar("_ReturnT_inner_co", covariant=True)

Ts = TypeVarTuple("Ts")


class MonoClassCall(Protocol[Unpack[Ts], _ReturnT_co]):
    def call(self, *args: Unpack[Ts]) -> Coroutine[Any, Any, _ReturnT_co]: ...


class StreamingClassCall(Protocol[Unpack[Ts], _ReturnT_co]):
    def call(self, *args: Unpack[Ts]) -> AsyncGenerator[_ReturnT_co, None]: ...


class ClassCall(Protocol[Unpack[Ts], _ReturnT_co]):
    def call(
        self, *args: Unpack[Ts]
    ) -> Union[Coroutine[Any, Any, _ReturnT_co], AsyncGenerator[_ReturnT_co, None]]: ...


def create_class_node_subclass_single(
    cls: type[ClassCall[Unpack[Ts], _ReturnT_co]],
    stream_in: list[str],
) -> (
    type[MonoNode[Unpack[tuple[object, ...]], tuple[_ReturnT_co]]]
    | type[StreamingNode[Unpack[tuple[object, ...]], tuple[_ReturnT_co]]]
):
    """
    Create a DraftNode subclass for a class with a single output.

    Args:
        cls: The class to transform
        stream_in: List of input streams

    Returns:
        A DraftNode subclass
    """
    initial_state = {}
    for name in dir(cls):
        if not name.startswith("__"):
            val = getattr(cls, name)
            if not callable(val):
                initial_state[name] = val

    class_name = f"{cls.__name__}__Stateful_Node"
    bases = (DraftNode, cls)
    class_dict = {}

    def __init__(self, *args, **kwargs):
        for field, initial_val in initial_state.items():
            setattr(self, field, initial_val)
        DraftNode.__init__(self, *args, **kwargs)

    class_dict["__init__"] = __init__

    def call(self, *args, **kwargs):
        result = cls.call(self, *args, **kwargs)
        if isinstance(result, Coroutine):
            return wrap_coroutine_tuple(result)
        elif isinstance(result, AsyncGenerator):
            return wrap_async_generator_tuple(result)
        else:
            raise ValueError("User method must return an async def")

    class_dict["call"] = call

    default_values = {}
    minimum_run_level: list[RunLevel] = []
    sig = signature(cls.call)
    for index, param in enumerate(sig.parameters.values()):
        if param.name == "self" and index != 0 or index == 0 and param.name != "self":
            raise ValueError("First parameter must be 'self'")
        if param.name == "self" and index == 0:
            continue
        if param.kind in (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD):
            continue
        if param.default is not Parameter.empty:
            default_values[index - 1] = param.default
        if param.name in stream_in:
            minimum_run_level.append(1)
        else:
            minimum_run_level.append(0)

    func_params = sig.parameters.values()
    filename = cls.call.__code__.co_filename
    lineno = cls.call.__code__.co_firstlineno
    func_name = cls.call.__name__

    dynamic_cls = type(class_name, bases, class_dict)

    dynamic_cls._initial_state = initial_state
    dynamic_cls._default_values = default_values
    dynamic_cls._minimum_run_level = minimum_run_level
    dynamic_cls._original_signature = sig
    dynamic_cls._original_filename = filename
    dynamic_cls._original_lineno = lineno
    dynamic_cls._original_signature_name = func_name

    dynamic_cls._original_call = OriginalCall(
        call_signature=sig,
        call_code=cls.call.__code__,
        func_name=func_name,
        class_name=cls.__name__,
    )

    return dynamic_cls


def create_func_node_factory_single(
    func: (
        Callable[[Unpack[Ts]], Coroutine[object, object, _ReturnT_co]]
        | Callable[[Unpack[Ts]], AsyncGenerator[_ReturnT_co, None]]
    ),
    stream_in: list[str],
) -> type[DraftNode[Unpack[Ts], Tuple[_ReturnT_co]]]:
    """
    Create a DraftNode subclass for a function with a single output.

    Args:
        func: The function to transform
        stream_in: List of input streams

    Returns:
        A DraftNode subclass
    """
    logger.debug(f"Creating node class for function: {func}, with stream_in: {stream_in}")
    func_sig = signature(func)
    func_params = func_sig.parameters.values()
    filename = func.__code__.co_filename
    lineno = func.__code__.co_firstlineno
    func_name = func.__name__

    minimum_run_level: list[RunLevel] = []
    for arg in func_params:
        if arg.name in stream_in:
            minimum_run_level.append(1)
        else:
            minimum_run_level.append(0)

    default_values = {}

    for index, param in enumerate(func_params):
        default_value: object = param.default  # pyright: ignore[reportAny]
        if default_value is not Parameter.empty:
            default_values[index] = default_value
            logger.debug(f"Extracted default for parameter index {index}: {default_value}")
        else:
            logger.debug(f"No default for parameter index {index}")

    logger.debug(f"Final default_values: {default_values}")

    Ts_inner = TypeVarTuple("Ts_inner")

    class DynamicSimpleNode(DraftNode[Unpack[Ts_inner], Tuple[_ReturnT_inner_co]]):
        """Dynamically created node class for the decorated function.

        This class is created by the `@node` decorator and is used to create
        a new custom class that inherits from the `Node` class. The new class
        is created with the decorated function as the `call` method, with some
        special handling for Coroutines and AsyncGenerators and wrapping the
        output in a tuple.
        """

        _minimum_run_level = minimum_run_level
        _default_values = default_values
        _original_call = OriginalCall(
            call_signature=func_sig,
            call_code=func.__code__,
            func_name=func_name,
            class_name=None,
        )

        @override
        def call(
            self, *args: Unpack[Ts_inner]
        ) -> Coroutine[object, object, Tuple[_ReturnT_inner_co]] | AsyncGenerator[Tuple[_ReturnT_inner_co], None]:
            result = func(*cast(Tuple[Unpack[Ts]], args))
            casted_result: Coroutine[object, object, _ReturnT_inner_co] | AsyncGenerator[_ReturnT_inner_co, None] = (
                result  # pyright: ignore[reportAssignmentType]
            )
            if isinstance(casted_result, Awaitable):
                return wrap_coroutine_tuple(casted_result)
            elif isinstance(result, AsyncGenerator):
                return wrap_async_generator_tuple(casted_result)
            else:
                raise TypeError("Unexpected return type (must be async function)")

    DynamicSimpleNode.__name__ = func.__name__
    logger.debug(f"Created node class: {DynamicSimpleNode}, _default_values: {default_values}")
    return DynamicSimpleNode[Unpack[Ts], _ReturnT_co]
