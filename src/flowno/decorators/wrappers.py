from collections.abc import AsyncGenerator, Awaitable, Coroutine
from types import TracebackType
from typing import Any, TypeVar, overload
from typing_extensions import override

T1 = TypeVar('T1')

async def wrap_coroutine_tuple(co: Coroutine[Any, Any, T1]) -> tuple[T1]:
    return (await co,)


class AsyncGeneratorTupleWrapper(AsyncGenerator[tuple[T1], None]):
    """Wrapper that converts AsyncGenerator[T1, None] to AsyncGenerator[tuple[T1], None]"""
    
    def __init__(self, gen: AsyncGenerator[T1, None]) -> None:
        self._gen = gen
    
    @override
    def __aiter__(self) -> "AsyncGeneratorTupleWrapper[T1]":
        return self
    
    @override
    async def __anext__(self) -> tuple[T1]:
        try:
            value = await self._gen.__anext__()
            return (value,)
        except RuntimeError as e:
            # Python wraps StopAsyncIteration raised in async generators in RuntimeError
            # This happens even with custom event loops
            if isinstance(e.__cause__, StopAsyncIteration):
                # If there are args, wrap them in a tuple
                if e.__cause__.args:
                    raise StopAsyncIteration((e.__cause__.args[0],))
                else:
                    raise StopAsyncIteration()
            else:
                raise
        except StopAsyncIteration:
            # Natural end of iteration (generator exhausted without explicit raise)
            raise
    
    @override
    @overload
    async def athrow(
        self, typ: type[BaseException], val: BaseException | object = None, tb: TracebackType | None = None, /
    ) -> tuple[T1]: ...

    @override
    @overload
    async def athrow(self, typ: BaseException, val: None = None, tb: TracebackType | None = None, /) -> tuple[T1]: ...

    @override
    async def athrow(
        self,
        typ: BaseException | type[BaseException],
        val: BaseException | object | None = None,
        tb: TracebackType | None = None,
    ) -> tuple[T1]:
        try:
            if val is None:
                value = await self._gen.athrow(typ)
            else:
                assert isinstance(typ, type), "Expected a type for the exception type"
                value = await self._gen.athrow(typ, val, tb)
            return (value,)
        except RuntimeError as e:
            # Python wraps StopAsyncIteration raised in async generators in RuntimeError
            if isinstance(e.__cause__, StopAsyncIteration):
                # If there are args, wrap them in a tuple
                if e.__cause__.args:
                    raise StopAsyncIteration((e.__cause__.args[0],))
                else:
                    raise StopAsyncIteration()
            else:
                raise
        except StopAsyncIteration:
            # Natural end of iteration
            raise
    
    @override
    async def asend(self, value: None) -> tuple[T1]:
        try:
            result = await self._gen.asend(value)
            return (result,)
        except RuntimeError as e:
            # Python wraps StopAsyncIteration raised in async generators in RuntimeError
            if isinstance(e.__cause__, StopAsyncIteration):
                # If there are args, wrap them in a tuple
                if e.__cause__.args:
                    raise StopAsyncIteration((e.__cause__.args[0],))
                else:
                    raise StopAsyncIteration()
            else:
                raise
        except StopAsyncIteration:
            # Natural end of iteration
            raise
    
    @override
    async def aclose(self) -> None:
        await self._gen.aclose()


def wrap_async_generator_tuple(gen: AsyncGenerator[T1, None]) -> AsyncGenerator[tuple[T1], None]:
    return AsyncGeneratorTupleWrapper(gen)


class AsyncGeneratorDirectWrapper(AsyncGenerator[T1, None]):
    """Wrapper that forwards AsyncGenerator[T1, None] directly"""
    
    def __init__(self, gen: AsyncGenerator[T1, None]) -> None:
        self._gen = gen
    
    @override
    def __aiter__(self) -> "AsyncGeneratorDirectWrapper[T1]":
        return self
    
    @override
    async def __anext__(self) -> T1:
        return await self._gen.__anext__()
    
    @override
    @overload
    async def athrow(
        self, typ: type[BaseException], val: BaseException | object = None, tb: TracebackType | None = None, /
    ) -> T1: ...

    @override
    @overload
    async def athrow(self, typ: BaseException, val: None = None, tb: TracebackType | None = None, /) -> T1: ...

    @override
    async def athrow(
        self,
        typ: BaseException | type[BaseException],
        val: BaseException | object | None = None,
        tb: TracebackType | None = None,
    ) -> T1:
        if val is None:
            return await self._gen.athrow(typ)
        else:
            assert isinstance(typ, type), "Expected a type for the exception type"
            return await self._gen.athrow(typ, val, tb)
    
    @override
    async def asend(self, value: None) -> T1:
        return await self._gen.asend(value)
    
    @override
    async def aclose(self) -> None:
        await self._gen.aclose()


def wrap_async_generator_direct(ag: AsyncGenerator[T1, None]) -> AsyncGenerator[T1, None]:
    return AsyncGeneratorDirectWrapper(ag)
