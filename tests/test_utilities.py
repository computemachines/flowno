import logging
from collections.abc import AsyncGenerator, Generator
from types import coroutine

import pytest
from flowno import EventLoop, sleep
from flowno.core.types import Generation, RunLevel
from flowno.utilities.coroutine_wrapper import CoroutineWrapper
from flowno.utilities.helpers import clip_generation, cmp_generation, inc_generation
from flowno.utilities.logging import log_async
from pytest import LogCaptureFixture, raises


@coroutine
def constant_co(value: int) -> Generator[int, None, str]:
    yield value
    return "Done"


async def constant(value: int) -> str:
    return await constant_co(value)


async def simple_async_function(value: int) -> int:
    return value


async def simple_async_generator(value: int) -> AsyncGenerator[int, None]:
    yield value
    return


def test_coroutine_wrapper_execution():
    # Create a coroutine wrapper around the constant coroutine
    wrapped_coroutine = CoroutineWrapper(constant(42), "constant", "42")

    yielded = wrapped_coroutine.send(None)
    assert yielded == 42
    with raises(StopIteration) as exc_info:
        wrapped_coroutine.send(None)
    assert exc_info.value.value == "Done"


def test_log_async_with_coroutine(caplog: LogCaptureFixture):
    # Set the logging level to capture debug logs
    caplog.set_level(logging.DEBUG)

    # Initialize your custom event loop
    event_loop = EventLoop()

    # Define a coroutine function decorated with @log_async
    @log_async
    async def test_coroutine():
        _ = await sleep(0.1)
        return "Test Completed"

    # Create the root task
    root_task = test_coroutine()

    # Run the event loop until the root task is complete
    _ = event_loop.run_until_complete(root_task, join=True)

    # Assert that the coroutine returned the expected result
    assert event_loop.finished[root_task] == "Test Completed"

    # Extract the log messages
    log_messages = [record.message for record in caplog.records]

    # Check that the logs include the expected messages for `test_coroutine`
    assert any("Calling function: test_coroutine()" in msg for msg in log_messages)
    assert any("Resuming coroutine: test_coroutine() with send(None)" in msg for msg in log_messages)
    assert any("Finished coroutine: test_coroutine() with result 'Test Completed'" in msg for msg in log_messages)


def test_log_async_awaited_values(caplog: LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    event_loop = EventLoop()

    @log_async
    async def constant_value(value: int) -> int:
        return value

    @log_async
    async def test_coroutine():
        co_dummy = constant_value(42)
        value = await co_dummy
        return value

    root_task = test_coroutine()
    _ = event_loop.run_until_complete(root_task, join=True)

    assert event_loop.finished[root_task] == 42

    log_messages = [record.message for record in caplog.records]

    # Assertions for each expected log message
    assert any("Calling function: test_coroutine()" in msg for msg in log_messages)
    assert any("test_coroutine() is a coroutine" in msg for msg in log_messages)
    assert any("Resuming coroutine: test_coroutine() with send(None)" in msg for msg in log_messages)
    assert any("Calling function: constant_value(42)" in msg for msg in log_messages)
    assert any("constant_value(42) is a coroutine" in msg for msg in log_messages)
    assert any("Starting coroutine: constant_value(42) via __await__" in msg for msg in log_messages)
    assert any("Coroutine constant_value(42) completed via __await__ with result 42" in msg for msg in log_messages)
    assert any("Finished coroutine: test_coroutine() with result 42" in msg for msg in log_messages)


@log_async
async def simple_async_gen(n: int) -> AsyncGenerator[int, None]:
    for i in range(n):
        yield i
    return


def test_simple_async_gen_logging(caplog: LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    event_loop = EventLoop()

    @log_async
    async def main():
        async for i in simple_async_gen(3):
            pass

    root_task = main()

    _ = event_loop.run_until_complete(root_task, join=True)

    log_messages = [record.message for record in caplog.records]

    # Assertions for each expected log message
    # Check that 'main()' is called and identified as a coroutine
    assert any("Calling function: main()" in msg for msg in log_messages)
    assert any("main() is a coroutine" in msg for msg in log_messages)

    # Check that 'simple_async_gen(3)' is called and identified as an async generator
    assert any("Calling function: simple_async_gen(3)" in msg for msg in log_messages)
    assert any("simple_async_gen(3) is an async generator" in msg for msg in log_messages)

    # Check that the async generator yields the expected values
    assert any("Async generator simple_async_gen(3) yielded 0" in msg for msg in log_messages)
    assert any("Async generator simple_async_gen(3) yielded 1" in msg for msg in log_messages)
    assert any("Async generator simple_async_gen(3) yielded 2" in msg for msg in log_messages)

    # Check that the async generator finishes
    assert any("Async generator simple_async_gen(3) finished" in msg for msg in log_messages)

    # Check that the main coroutine finishes
    assert any("Finished coroutine: main() with result None" in msg for msg in log_messages)


@pytest.mark.parametrize(
    "gen, run_level, expected",
    [
        # Test when gen is None
        (None, 0, (0,)),
        (None, 1, (0, 0)),
        (None, 2, (0, 0, 0)),
        # Test increment at run_level 0
        ((0,), 0, (1,)),
        ((5,), 0, (6,)),
        ((0, 0), 0, (0,)),
        ((1, 2), 0, (1,)),
        # Test increment at run_level 1
        ((0, 0), 1, (0, 1)),
        ((1, 2), 1, (1, 3)),
        ((0,), 1, (1, 0)),
        ((0, 0, 0), 1, (0, 0)),
        # Test increment at higher run levels
        ((0, 0, 0), 2, (0, 0, 1)),
        ((1, 2, 3), 2, (1, 2, 4)),
        ((0, 0), 2, (0, 1, 0)),
        # Test truncation of higher run levels
        ((1, 2, 3), 0, (1,)),
        ((1, 2, 3), 1, (1, 2)),
        # Test extending generation tuple
        ((1,), 2, (2, 0, 0)),
    ],
)
def test_inc_generation(gen: Generation, run_level: RunLevel, expected: Generation):
    result = inc_generation(gen, run_level)
    assert result == expected, f"inc_generation({gen}, {run_level}) == {result}, expected {expected}"


@pytest.mark.parametrize(
    "gen, run_level, expected",
    [
        ((0, 0), 2, (0, 0)),
        ((0, 0), 1, (0, 0)),
        ((0, 0), 0, None),
        ((1, 0), 1, (1, 0)),
        ((1, 0), 0, (0,)),
        (None, 0, None),
        (None, 1, None),
        ((1, 2, 3), 0, (0,)),
        ((1, 2, 3), 1, (1, 1)),
        ((1, 2, 3), 2, (1, 2, 3)),
        ((1, 2, 3), 3, (1, 2, 3)),
    ],
)
def test_clip_generation(gen: Generation, run_level: RunLevel, expected: Generation):
    result = clip_generation(gen, run_level)
    assert cmp_generation(result, gen) <= 0
    if result is not None:
        assert gen is not None, "clip_generation(None, run_level) should return None"
        assert len(result) <= run_level + 1, f"clip_generation({gen}, {run_level}) > {run_level + 1}"
        assert len(result) <= len(gen), f"clip_generation({gen}, {run_level}) > {len(gen)}"

    assert result == expected, f"clip_generation({gen}, {run_level}) == {result}, expected {expected}"
