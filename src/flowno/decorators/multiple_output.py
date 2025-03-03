"""
Multiple output node creation utilities for Flowno.

This module provides utilities for creating multiple output nodes, which are used
internally by the :py:mod:`flowno.decorators.node` module. These utilities help
transform async functions or classes into DraftNode subclasses with multiple outputs.

For more information and examples, see the :py:mod:`flowno.decorators.node` module.
"""

import inspect
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from typing import TypeVar, cast, Tuple
from typing_extensions import override, TypeVarTuple, Unpack

from flowno.core.node_base import DraftNode, OriginalCall
from flowno.core.types import RunLevel
from flowno.decorators.wrappers import wrap_async_generator_direct

logger = logging.getLogger(__name__)

Ts = TypeVarTuple('Ts')
ReturnTupleT_co = TypeVar('ReturnTupleT_co', bound=Tuple[object, ...], covariant=True)

def create_func_node_factory_multiple(
    func: (
        Callable[[Unpack[Ts]], Coroutine[object, object, ReturnTupleT_co]]
        | Callable[[Unpack[Ts]], AsyncGenerator[ReturnTupleT_co, None]]
    ),
    stream_in: list[str],
) -> type[DraftNode[Unpack[Ts], ReturnTupleT_co]]:
    """
    Create a DraftNode subclass for a function with multiple outputs.

    Args:
        func: The function to transform
        stream_in: List of input streams

    Returns:
        A DraftNode subclass
    """
    func_sig = inspect.signature(func)
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
        logger.debug(f"checking {func.__name__} param {param} for default value")
        default_value: object = param.default  # pyright: ignore[reportAny]
        if default_value is not inspect.Parameter.empty:
            default_values[index] = default_value

    Ts_inner = TypeVarTuple('Ts_inner')
    ReturnTupleT_inner_co = TypeVar('ReturnTupleT_inner_co', bound=Tuple[object, ...], covariant=True)

    class DynamicDirectNode(DraftNode[Unpack[Ts_inner], ReturnTupleT_inner_co]):
        """Dynamically created node class for the decorated function.

        This class is created by the `@node` decorator and is used to create
        a new custom class that inherits from the `Node` class. The new class
        is created with the decorated function as the `call` method.
        """

        _minimum_run_level = minimum_run_level
        _default_values = default_values
        _original_call = OriginalCall(
            func_sig,
            func.__code__,
            func_name,
            None
        )

        @override
        def call(
            self, *args: Unpack[Ts_inner]
        ) -> Coroutine[object, object, ReturnTupleT_inner_co] | AsyncGenerator[ReturnTupleT_inner_co, None]:
            result = func(*cast(Tuple[Unpack[Ts]], args))
            casted_result: (
                Coroutine[object, object, ReturnTupleT_inner_co] | AsyncGenerator[ReturnTupleT_inner_co, None]
            ) = cast(Coroutine[object, object, ReturnTupleT_inner_co] | AsyncGenerator[ReturnTupleT_inner_co, None], result)
            if isinstance(casted_result, Awaitable):
                return casted_result
            elif isinstance(result, AsyncGenerator):
                return wrap_async_generator_direct(casted_result)
            else:
                raise TypeError("Unexpected return type (must be async function)")

    DynamicDirectNode.__name__ = func.__name__

    return DynamicDirectNode[Unpack[Ts], ReturnTupleT_co]
