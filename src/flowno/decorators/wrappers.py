from collections.abc import AsyncGenerator, Awaitable, Coroutine
from typing import Any, TypeVar

T1 = TypeVar('T1')

async def wrap_coroutine_tuple(co: Coroutine[Any, Any, T1]) -> tuple[T1]:
    return (await co,)


async def wrap_async_generator_tuple(
    gen: AsyncGenerator[T1, None]) -> AsyncGenerator[tuple[T1], None]:
    try:
        async for value in gen:
            yield (value,)
    except RuntimeError as e:
        if isinstance(e.__cause__, StopAsyncIteration):
            raise StopAsyncIteration((e.__cause__.args[0],)) from e.__cause__
        else:
            raise e


async def wrap_async_generator_direct(ag: AsyncGenerator[T1, None]) -> AsyncGenerator[T1, None]:
    try:
        async for x in ag:
            yield x
    except RuntimeError as e:
        if isinstance(e.__cause__, StopAsyncIteration):
            raise StopAsyncIteration((e.__cause__.args[0],)) from e.__cause__
        else:
            raise e
