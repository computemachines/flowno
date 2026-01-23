"""
Additional edge case tests for task cancellation (GitHub Issue #3).

Tests for advanced scenarios like:
- Cancelling tasks in different wait states
- Multiple cancellations
- Interaction with other primitives
- Race conditions
"""

import pytest
from flowno import sleep, spawn, Event, Lock, AsyncQueue
from flowno.core.event_loop.event_loop import EventLoop
from flowno.core.event_loop.tasks import TaskCancelled


class TestCancelTaskInVariousStates:
    """Test cancellation of tasks in different waiting states."""

    def test_cancel_task_waiting_on_sleep(self):
        """Cancel a task that's blocked on sleep."""
        cancelled_flag = []

        async def sleeper():
            try:
                await sleep(100.0)  # Long sleep
                return "should not reach"
            except TaskCancelled:
                cancelled_flag.append(True)
                return "cancelled while sleeping"

        async def main():
            handle = await spawn(sleeper())
            await sleep(0.01)  # Let it start sleeping
            result = await handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "cancelled while sleeping"
        assert cancelled_flag == [True]

    def test_cancel_task_waiting_on_event(self):
        """Cancel a task that's blocked waiting for an event."""
        event = Event()
        cancelled_flag = []

        async def waiter():
            try:
                await event.wait()
                return "should not reach"
            except TaskCancelled:
                cancelled_flag.append(True)
                return "cancelled while waiting"

        async def main():
            handle = await spawn(waiter())
            await sleep(0.01)  # Let it start waiting
            result = await handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "cancelled while waiting"
        assert cancelled_flag == [True]

    def test_cancel_task_waiting_on_lock(self):
        """Cancel a task that's blocked waiting for a lock."""
        lock = Lock()
        cancelled_flag = []

        async def lock_waiter():
            try:
                async with lock:
                    return "should not reach"
            except TaskCancelled:
                cancelled_flag.append(True)
                return "cancelled while waiting for lock"

        async def main():
            # Acquire lock in main task
            async with lock:
                handle = await spawn(lock_waiter())
                await sleep(0.01)  # Let it start waiting on lock
                result = await handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "cancelled while waiting for lock"
        assert cancelled_flag == [True]

    def test_cancel_task_waiting_on_queue(self):
        """Cancel a task that's blocked waiting on an empty queue."""
        queue = AsyncQueue[int]()
        cancelled_flag = []

        async def queue_waiter():
            try:
                await queue.get()
                return "should not reach"
            except TaskCancelled:
                cancelled_flag.append(True)
                return "cancelled while waiting on queue"

        async def main():
            handle = await spawn(queue_waiter())
            await sleep(0.01)  # Let it start waiting
            result = await handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "cancelled while waiting on queue"
        assert cancelled_flag == [True]


class TestMultipleCancellations:
    """Test cancelling a task multiple times or joining after cancel."""

    def test_cancel_same_task_twice(self):
        """Cancelling an already-cancelled task returns its result."""

        async def worker():
            try:
                await sleep(10.0)
            except TaskCancelled:
                return "first cancel"

        async def main():
            handle = await spawn(worker())
            await sleep(0.01)
            result1 = await handle.cancel()
            # Second cancel on an already finished (cancelled) task
            result2 = await handle.cancel()
            return (result1, result2)

        loop = EventLoop()
        result1, result2 = loop.run_until_complete(main(), join=True)
        assert result1 == "first cancel"
        assert result2 == "first cancel"

    def test_join_after_cancel(self):
        """Joining a cancelled task raises TaskCancelled."""

        async def worker():
            try:
                await sleep(10.0)
            except TaskCancelled:
                # Don't catch, let it propagate
                raise

        async def main():
            handle = await spawn(worker())
            await sleep(0.01)
            await handle.cancel()
            # Now try to join - should raise TaskCancelled
            await handle.join()

        loop = EventLoop()
        with pytest.raises(TaskCancelled):
            loop.run_until_complete(main(), join=True)

    def test_cancel_without_awaiting(self):
        """Task gets cancelled even if we don't await the cancel() result."""
        execution_log = []

        async def worker():
            execution_log.append("started")
            try:
                await sleep(10.0)
            except TaskCancelled:
                execution_log.append("cancelled")
            finally:
                execution_log.append("cleaned up")

        async def main():
            handle = await spawn(worker())
            await sleep(0.01)
            # Call cancel but don't await it
            _ = handle.cancel()
            # Give it time to process cancellation
            await sleep(0.05)
            return "done"

        loop = EventLoop()
        loop.run_until_complete(main(), join=True)
        assert "started" in execution_log
        assert "cancelled" in execution_log
        assert "cleaned up" in execution_log


class TestCancellationWithSpawnedTasks:
    """Test cancelling tasks that spawn other tasks."""

    def test_cancel_task_with_spawned_children(self):
        """Cancelling parent doesn't automatically cancel children."""
        child_log = []
        parent_log = []

        async def child():
            child_log.append("child started")
            await sleep(0.5)
            child_log.append("child finished")
            return "child result"

        async def parent():
            parent_log.append("parent started")
            child_handle = await spawn(child())
            try:
                await sleep(10.0)
            except TaskCancelled:
                parent_log.append("parent cancelled")
                # Child should still be running
                child_result = await child_handle.join()
                return f"parent cancelled, child: {child_result}"

        async def main():
            parent_handle = await spawn(parent())
            await sleep(0.01)
            result = await parent_handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert "parent started" in parent_log
        assert "parent cancelled" in parent_log
        assert "child started" in child_log
        assert "child finished" in child_log
        assert "child: child result" in result

    def test_cancel_and_cancel_children(self):
        """Parent can cancel its children during cleanup."""
        child_log = []

        async def child():
            try:
                await sleep(10.0)
            except TaskCancelled:
                child_log.append("child cancelled")
                return "child cancelled"

        async def parent():
            child_handle = await spawn(child())
            try:
                await sleep(10.0)
            except TaskCancelled:
                # Cancel child during cleanup
                child_result = await child_handle.cancel()
                return f"both cancelled: {child_result}"

        async def main():
            parent_handle = await spawn(parent())
            await sleep(0.01)
            result = await parent_handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert "child cancelled" in child_log
        assert "both cancelled: child cancelled" == result


class TestCancellationRaceConditions:
    """Test edge cases with timing and race conditions."""

    def test_cancel_task_that_just_finished(self):
        """Cancelling a task right after it finishes returns its result."""

        async def quick_task():
            await sleep(0.01)
            return "finished naturally"

        async def main():
            handle = await spawn(quick_task())
            await sleep(0.02)  # Let it finish
            # Task is already done
            result = await handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == "finished naturally"

    def test_cancel_task_that_errors(self):
        """Cancelling a task that already errored returns the error."""

        async def error_task():
            await sleep(0.01)
            raise ValueError("task error")

        async def main():
            handle = await spawn(error_task())
            await sleep(0.02)  # Let it error
            # Task already errored
            await handle.cancel()

        loop = EventLoop()
        with pytest.raises(ValueError, match="task error"):
            loop.run_until_complete(main(), join=True)


class TestCancellationReturnValues:
    """Test various return value scenarios."""

    def test_cancel_task_with_no_return(self):
        """Task that doesn't return gets None."""

        async def no_return_task():
            try:
                await sleep(10.0)
            except TaskCancelled:
                pass  # No return

        async def main():
            handle = await spawn(no_return_task())
            await sleep(0.01)
            result = await handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result is None

    def test_cancel_task_returns_complex_object(self):
        """Cancelled task can return complex objects."""

        async def returns_dict():
            try:
                await sleep(10.0)
            except TaskCancelled:
                return {"status": "cancelled", "data": [1, 2, 3]}

        async def main():
            handle = await spawn(returns_dict())
            await sleep(0.01)
            result = await handle.cancel()
            return result

        loop = EventLoop()
        result = loop.run_until_complete(main(), join=True)
        assert result == {"status": "cancelled", "data": [1, 2, 3]}

    def test_cancel_propagates_through_try_except_else(self):
        """TaskCancelled propagates correctly through try/except/else."""

        async def try_except_else_task():
            try:
                await sleep(10.0)
            except TaskCancelled:
                # Re-raise to test else isn't executed
                raise
            else:
                return "else should not run"

        async def main():
            handle = await spawn(try_except_else_task())
            await sleep(0.01)
            await handle.cancel()

        loop = EventLoop()
        # Should get None since TaskCancelled propagated
        result = loop.run_until_complete(main(), join=True)
        assert result is None
