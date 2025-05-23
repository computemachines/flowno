"""
Tests for the event loop exit primitive.
"""
import pytest
from flowno import EventLoop, exit, sleep, spawn


def test_exit_simple():
    loop = EventLoop()

    async def early_exit():
        print("About to exit")
        await exit()
        print("This will never be executed")

    # The loop should exit cleanly
    loop.run_until_complete(early_exit())


def test_exit_with_value():
    loop = EventLoop()

    async def exit_with_result():
        await sleep(0.1)  # Small delay
        await exit("success")

    # The exit value should be returned when join=True
    result = loop.run_until_complete(exit_with_result(), join=True)
    assert result == "success"


def test_exit_with_exception():
    loop = EventLoop()

    async def exit_with_error():
        await exit(exception=ValueError("Test error"))

    # The exception should be propagated
    with pytest.raises(ValueError, match="Test error"):
        loop.run_until_complete(exit_with_error(), join=True)


def test_exit_with_multiple_tasks():
    loop = EventLoop()

    async def task_to_exit():
        await sleep(0.1)  # Small delay
        await exit("early exit")
        return "never returns"

    async def other_task():
        # This task should not complete when the event loop exits
        await sleep(1)
        return "completed"

    async def main():
        t1 = await spawn(task_to_exit())
        t2 = await spawn(other_task())
        # We should exit before these joins complete
        await t1.join()
        await t2.join()
        return "main completed"

    # The event loop should exit with the value from the exit() call
    result = loop.run_until_complete(main(), join=True)
    assert result == "early exit"
