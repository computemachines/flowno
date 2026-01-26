"""Tests for threading primitives in the Flowno event loop."""

import time
from time import sleep as blocking_sleep

import pytest
from flowno import EventLoop, AsyncQueue, sleep, current_event_loop, spawn_thread, ThreadHandle
from flowno.core.event_loop.queues import QueueClosedError


def test_spawn_thread_basic():
    """Test basic spawn_thread functionality with a simple async function."""
    loop = EventLoop()

    async def worker():
        """A simple worker that returns a value."""
        return "hello from thread"

    async def main():
        handle = spawn_thread(worker)
        result = await handle.join()
        return result

    result = loop.run_until_complete(main(), join=True)
    assert result == "hello from thread"


def test_spawn_thread_with_args():
    """Test spawn_thread with arguments."""
    loop = EventLoop()

    async def worker(a: int, b: int) -> int:
        return a + b

    async def main():
        handle = spawn_thread(worker, args=(10, 20))
        result = await handle.join()
        return result

    result = loop.run_until_complete(main(), join=True)
    assert result == 30


def test_spawn_thread_with_kwargs():
    """Test spawn_thread with keyword arguments."""
    loop = EventLoop()

    async def worker(greeting: str, name: str) -> str:
        return f"{greeting}, {name}!"

    async def main():
        handle = spawn_thread(worker, args=("Hello",), kwargs={"name": "World"})
        result = await handle.join()
        return result

    result = loop.run_until_complete(main(), join=True)
    assert result == "Hello, World!"


def test_spawn_thread_blocking_work():
    """Test that blocking operations in thread don't block main event loop."""
    loop = EventLoop()
    events = []

    async def worker(delay: float):
        """Worker that does blocking work."""
        blocking_sleep(delay)  # Blocking sleep
        return "done"

    async def main():
        start = time.time()

        # Spawn two workers in separate threads
        handle1 = spawn_thread(worker, args=(0.3,))
        handle2 = spawn_thread(worker, args=(0.3,))

        # Both should run concurrently
        result1 = await handle1.join()
        result2 = await handle2.join()

        elapsed = time.time() - start

        # Should complete in ~0.3s (parallel), not ~0.6s (sequential)
        return elapsed, result1, result2

    elapsed, r1, r2 = loop.run_until_complete(main(), join=True)
    assert r1 == "done"
    assert r2 == "done"
    # Allow some tolerance for thread overhead
    assert elapsed < 0.5, f"Expected parallel execution, but took {elapsed:.2f}s"


def test_spawn_thread_with_queue():
    """Test communication between thread and main event loop via queue."""
    loop = EventLoop()

    async def worker(queue: AsyncQueue, main_loop: EventLoop):
        """Worker that produces items and sends to main loop."""
        for i in range(5):
            blocking_sleep(0.05)  # Simulate blocking work
            queue.put_threadsafe(i * 2, main_loop)
        queue.close_threadsafe(main_loop)
        return "producer done"

    async def main():
        main_loop = current_event_loop()
        assert main_loop is not None

        queue: AsyncQueue[int] = AsyncQueue()
        handle = spawn_thread(worker, args=(queue, main_loop))

        results = []
        async for item in queue:
            results.append(item)

        producer_result = await handle.join()
        return results, producer_result

    results, producer_result = loop.run_until_complete(main(), join=True)
    assert results == [0, 2, 4, 6, 8]
    assert producer_result == "producer done"


def test_spawn_thread_exception():
    """Test that exceptions in spawned threads are properly propagated."""
    loop = EventLoop()

    async def failing_worker():
        blocking_sleep(0.1)
        raise ValueError("Something went wrong")

    async def main():
        handle = spawn_thread(failing_worker)
        return await handle.join()

    with pytest.raises(ValueError, match="Something went wrong"):
        loop.run_until_complete(main(), join=True)


def test_spawn_thread_handle_properties():
    """Test ThreadHandle property methods."""
    loop = EventLoop()

    async def slow_worker():
        blocking_sleep(0.3)
        return "done"

    async def main():
        handle = spawn_thread(slow_worker)

        # Give thread time to start
        await sleep(0.05)

        # Initially should be alive and not finished
        assert handle.is_alive
        assert not handle.is_finished
        assert not handle.is_error

        # Wait for completion
        result = await handle.join()

        # After completion - give thread time to terminate
        await sleep(0.05)
        assert not handle.is_alive
        assert handle.is_finished
        assert not handle.is_error

        return result

    result = loop.run_until_complete(main(), join=True)
    assert result == "done"


def test_queue_put_threadsafe_basic():
    """Test basic put_threadsafe functionality."""
    import threading

    loop = EventLoop()
    results = []

    async def consumer(queue: AsyncQueue[int]):
        """Consume items from queue."""
        async for item in queue:
            results.append(item)

    async def main():
        main_loop = current_event_loop()
        assert main_loop is not None

        queue: AsyncQueue[int] = AsyncQueue()

        def producer_thread():
            for i in range(3):
                blocking_sleep(0.05)
                queue.put_threadsafe(i, main_loop)
            queue.close_threadsafe(main_loop)

        # Start consumer task
        from flowno import spawn
        consumer_task = await spawn(consumer(queue))

        # Start producer thread
        thread = threading.Thread(target=producer_thread)
        thread.start()

        # Wait for consumer to finish
        await consumer_task.join()

        # Wait for thread to finish
        thread.join()

    loop.run_until_complete(main(), join=True)
    assert results == [0, 1, 2]


def test_queue_close_threadsafe():
    """Test that close_threadsafe properly wakes up waiting consumers."""
    import threading

    loop = EventLoop()

    async def consumer(queue: AsyncQueue[str]):
        """Consume items, will block waiting for items."""
        items = []
        try:
            async for item in queue:
                items.append(item)
        except Exception:
            pass
        return items

    async def main():
        main_loop = current_event_loop()
        assert main_loop is not None

        queue: AsyncQueue[str] = AsyncQueue()

        def producer_thread():
            blocking_sleep(0.1)
            queue.put_threadsafe("item1", main_loop)
            blocking_sleep(0.1)
            queue.close_threadsafe(main_loop)

        # Start consumer task
        from flowno import spawn
        consumer_task = await spawn(consumer(queue))

        # Start producer thread
        thread = threading.Thread(target=producer_thread)
        thread.start()

        # Wait for consumer to finish
        result = await consumer_task.join()

        # Wait for thread to finish
        thread.join()

        return result

    result = loop.run_until_complete(main(), join=True)
    assert result == ["item1"]


def test_multiple_threads_same_queue():
    """Test multiple threads writing to the same queue."""
    loop = EventLoop()

    async def main():
        main_loop = current_event_loop()
        assert main_loop is not None

        queue: AsyncQueue[str] = AsyncQueue()
        num_threads = 3
        items_per_thread = 5

        async def worker(worker_id: int, q: AsyncQueue, target: EventLoop):
            for i in range(items_per_thread):
                blocking_sleep(0.01)
                q.put_threadsafe(f"w{worker_id}-{i}", target)

        # Start multiple threads
        handles = []
        for i in range(num_threads):
            handle = spawn_thread(worker, args=(i, queue, main_loop))
            handles.append(handle)

        # Wait for all threads to complete
        for handle in handles:
            await handle.join()

        # Close the queue after all producers are done
        await queue.close()

        # Collect all items
        items = list(queue.items)

        return items

    items = loop.run_until_complete(main(), join=True)

    # Should have items from all threads
    assert len(items) == 15  # 3 threads * 5 items each


def test_thread_local_event_loop():
    """Test that each thread gets its own event loop."""
    import threading

    main_loop = None
    thread_loop = None
    loops_different = None

    def thread_func():
        nonlocal thread_loop, loops_different
        inner_loop = EventLoop()

        async def check_loop():
            nonlocal thread_loop
            thread_loop = current_event_loop()
            return thread_loop

        inner_loop.run_until_complete(check_loop(), join=True)

        # Compare after both are set
        if main_loop is not None and thread_loop is not None:
            loops_different = main_loop is not thread_loop

    main_event_loop = EventLoop()

    async def main():
        nonlocal main_loop
        main_loop = current_event_loop()

        # Start thread that creates its own event loop
        thread = threading.Thread(target=thread_func)
        thread.start()

        # Wait for thread with polling
        while thread.is_alive():
            await sleep(0.01)

        return main_loop

    main_event_loop.run_until_complete(main(), join=True)

    # Both should have had event loops
    assert main_loop is not None
    assert thread_loop is not None
    # They should be different instances
    assert main_loop is not thread_loop


def test_create_task_from_thread():
    """Test that create_task works when called from another thread."""
    import threading

    loop = EventLoop()
    results = []

    async def background_task(value: int):
        """Task that gets scheduled from another thread."""
        results.append(value)
        return value * 2

    async def main():
        main_loop = current_event_loop()
        assert main_loop is not None

        def thread_func():
            # Schedule tasks from this thread
            for i in range(3):
                blocking_sleep(0.05)
                main_loop.create_task(background_task(i))

        # Start the thread
        thread = threading.Thread(target=thread_func)
        thread.start()

        # Wait for thread to finish and tasks to process
        while thread.is_alive():
            await sleep(0.01)

        # Give scheduled tasks time to run
        await sleep(0.1)

        return results

    loop.run_until_complete(main(), join=True)
    assert sorted(results) == [0, 1, 2]


def test_thread_handle_timeout():
    """Test ThreadHandle.join with timeout."""
    loop = EventLoop()

    async def slow_worker():
        blocking_sleep(1.0)  # Long sleep
        return "done"

    async def main():
        handle = spawn_thread(slow_worker)

        with pytest.raises(TimeoutError):
            await handle.join(timeout=0.1)

    loop.run_until_complete(main(), join=True)


def test_spawn_thread_async_operations():
    """Test that spawned threads can perform async operations internally."""
    loop = EventLoop()

    async def worker_with_async():
        """Worker that uses async operations in its own event loop."""
        # This runs in a separate event loop
        results = []
        for i in range(3):
            # Using flowno's sleep in the thread's event loop
            await sleep(0.05)
            results.append(i)
        return results

    async def main():
        handle = spawn_thread(worker_with_async)
        result = await handle.join()
        return result

    result = loop.run_until_complete(main(), join=True)
    assert result == [0, 1, 2]
