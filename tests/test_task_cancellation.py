"""
Tests for task cancellation feature (GitHub Issue #3).

This file contains tests for the awaitable cancel() method on TaskHandle.
The feature allows:
1. A task to be cancelled via `await handle.cancel()`
2. The cancelled task to catch TaskCancelled and do cleanup
3. The cancelled task to return a value that propagates to the canceller

Example from issue #3:
    async def worker():
        print("doing work")
        try:
            _ = await sleep(1.0)
        except TaskCancelled:
            print("worker cancelled")
        finally:
            print("doing more work... done.")
            return 42

    async def main():
        handle = await spawn(worker())
        print("doing work on main task")
        _ = await sleep(0.5)
        print("cancelling worker")
        value = await handle.cancel()
        print(f"received {value} from cancelled worker")
"""

import pytest
from flowno import sleep, spawn
from flowno.core.event_loop.event_loop import EventLoop
from flowno.core.event_loop.tasks import TaskCancelled


class TestAwaitableCancel:
    """Tests for the awaitable cancel() method."""

    def test_cancel_returns_value_from_finally(self):
        """Cancelled task can return a value from finally block."""

        async def worker():
            try:
                await sleep(10.0)  # Long sleep - will be cancelled
            except TaskCancelled:
                pass
            finally:
                return 42

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)  # Let worker start
            value = await handle.cancel()
            return value

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == 42

    def test_cancel_returns_value_from_except_block(self):
        """Cancelled task can return a value from except block."""

        async def worker():
            try:
                await sleep(10.0)
            except TaskCancelled:
                return "cancelled gracefully"

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)
            value = await handle.cancel()
            return value

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "cancelled gracefully"

    def test_cancel_propagates_exception_from_handler(self):
        """If cancelled task raises during cleanup, it propagates to canceller."""

        async def worker():
            try:
                await sleep(10.0)
            except TaskCancelled:
                raise ValueError("cleanup failed")

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)
            await handle.cancel()  # Should raise ValueError

        loop = EventLoop()
        with pytest.raises(ValueError, match="cleanup failed"):
            loop.run_until_complete(main(), join=True)

    def test_cancel_already_finished_task(self):
        """Cancelling a finished task returns its result."""

        async def worker():
            return "done"

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)  # Let it finish
            value = await handle.cancel()
            return value

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "done"

    def test_cancel_is_awaitable(self):
        """The cancel() method should be awaitable, not just return bool."""

        async def worker():
            await sleep(10.0)

        async def main():
            handle = await spawn(worker())
            # This should be awaitable
            result = handle.cancel()
            # Check if it's a coroutine/generator (awaitable)
            assert hasattr(result, '__next__') or hasattr(result, '__await__'), \
                "cancel() should return an awaitable"

        loop = EventLoop()
        loop.run_until_complete(main(), join=True)


class TestTaskCancelledExceptionInTask:
    """Tests for TaskCancelled exception behavior inside tasks."""

    def test_task_receives_cancelled_exception(self):
        """Task should receive TaskCancelled when cancelled."""
        received_exception = []

        async def worker():
            try:
                await sleep(10.0)
            except TaskCancelled as e:
                received_exception.append(e)
                return "caught"

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)
            await handle.cancel()

        loop = EventLoop()
        loop.run_until_complete(main(), join=True)
        assert len(received_exception) == 1
        assert isinstance(received_exception[0], TaskCancelled)

    def test_nested_await_receives_cancelled(self):
        """TaskCancelled should propagate through nested awaits."""

        async def inner():
            await sleep(10.0)

        async def worker():
            try:
                await inner()
            except TaskCancelled:
                return "caught in outer"

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)
            value = await handle.cancel()
            return value

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "caught in outer"


class TestCancelWithCleanup:
    """Tests for cleanup behavior during cancellation."""

    def test_finally_runs_on_cancel(self):
        """Finally block should run when task is cancelled."""
        cleanup_ran = []

        async def worker():
            try:
                await sleep(10.0)
            finally:
                cleanup_ran.append(True)

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)
            await handle.cancel()

        loop = EventLoop()
        loop.run_until_complete(main(), join=True)
        assert cleanup_ran == [True]

    def test_multiple_finally_blocks_run(self):
        """All finally blocks in the call stack should run."""
        cleanup_order = []

        async def inner():
            try:
                await sleep(10.0)
            finally:
                cleanup_order.append("inner")

        async def worker():
            try:
                await inner()
            finally:
                cleanup_order.append("outer")

        async def main():
            handle = await spawn(worker())
            await sleep(0.1)
            await handle.cancel()

        loop = EventLoop()
        loop.run_until_complete(main(), join=True)
        assert cleanup_order == ["inner", "outer"]
