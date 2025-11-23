"""Tests for direct threading API - spawn_in_thread()"""

import time
import threading
from timeit import timeit
from flowno.core.event_loop import EventLoop, sleep, spawn_in_thread
from flowno import AsyncQueue


def test_spawn_in_thread_basic():
    """Test basic spawn_in_thread with simple blocking function"""
    loop = EventLoop()

    def blocking_work(x):
        time.sleep(0.1)
        return x * 2

    async def main():
        handle = await spawn_in_thread(blocking_work, 21)
        result = await handle.join()
        assert result == 42

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.09 <= actual <= 0.25  # ~0.1s sleep + overhead


def test_spawn_in_thread_multiple():
    """Test spawning multiple threads concurrently"""
    loop = EventLoop()

    def blocking_work(x, delay):
        time.sleep(delay)
        return x * 2

    async def main():
        # Spawn 3 threads concurrently
        task1 = await spawn_in_thread(blocking_work, 1, 0.1)
        task2 = await spawn_in_thread(blocking_work, 2, 0.15)
        task3 = await spawn_in_thread(blocking_work, 3, 0.05)

        # Results should arrive based on delay, not spawn order
        result3 = await task3.join()
        result1 = await task1.join()
        result2 = await task2.join()

        assert result1 == 2
        assert result2 == 4
        assert result3 == 6

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.14 <= actual <= 0.35  # longest thread 0.15s


def test_spawn_in_thread_with_exception():
    """Test that exceptions in threads are propagated back"""
    loop = EventLoop()

    def failing_work():
        time.sleep(0.05)
        raise ValueError("Thread error!")

    async def main():
        handle = await spawn_in_thread(failing_work)
        try:
            result = await handle.join()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert str(e) == "Thread error!"

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.04 <= actual <= 0.2  # ~0.05s sleep then exception


def test_spawn_in_thread_with_kwargs():
    """Test spawn_in_thread with keyword arguments"""
    loop = EventLoop()

    def work_with_kwargs(a, b, c=0, d=0):
        return a + b + c + d

    async def main():
        handle = await spawn_in_thread(work_with_kwargs, 1, 2, c=3, d=4)
        result = await handle.join()
        assert result == 10

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.0 <= actual <= 0.15  # no intentional sleep


def test_spawn_in_thread_main_loop_continues():
    """Test that main loop continues while thread is blocking"""
    loop = EventLoop()

    log = []
    start_time = time.time()

    def append_log(msg):
        log.append((time.time() - start_time, msg))

    def blocking_work():
        append_log("Thread started")
        time.sleep(0.2)
        append_log("Thread done")
        return "result"

    async def main():
        append_log("Main start")

        # Spawn blocking work in thread
        from flowno.core.event_loop import spawn
        task = await spawn_in_thread(blocking_work)

        # Main loop should continue while thread blocks
        append_log("After spawn")
        await sleep(0.05)
        append_log("After sleep 1")
        await sleep(0.05)
        append_log("After sleep 2")

        # Wait for thread result
        result = await task.join()
        append_log(f"Got result: {result}")

        assert result == "result"

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.18 <= actual <= 0.35  # thread 0.2s + two 0.05s sleeps interleaved

    # Verify main loop kept running while thread blocked
    msgs = [msg for _, msg in log]
    # Thread can start before or after "After spawn" due to OS thread scheduling
    assert msgs in [
        [
            "Main start",
            "After spawn",
            "Thread started",
            "After sleep 1",
            "After sleep 2",
            "Thread done",
            "Got result: result",
        ],
        [
            "Main start",
            "Thread started",
            "After spawn",
            "After sleep 1",
            "After sleep 2",
            "Thread done",
            "Got result: result",
        ],
    ]


def test_spawn_in_thread_with_queue_communication():
    """Test thread sending progress updates via queue"""
    loop = EventLoop()

    def worker_with_updates(main_loop, queue, count):
        """Worker that sends progress updates back to main loop"""
        for i in range(count):
            time.sleep(0.05)
            # Send update back to main loop
            main_loop.create_task(queue.put(f"progress {i}"))
        return "done"

    async def main():
        queue = AsyncQueue()

        # Spawn worker with queue access
        from flowno.core.event_loop import spawn, current_event_loop
        loop = current_event_loop()
        task = await spawn_in_thread(worker_with_updates, loop, queue, 3)

        # Collect progress updates
        updates = []
        for _ in range(3):
            update = await queue.get()
            updates.append(update)

        # Get final result
        result = await task.join()

        assert updates == ["progress 0", "progress 1", "progress 2"]
        assert result == "done"

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.14 <= actual <= 0.35  # 3 * 0.05 sleeps


def test_spawn_in_thread_no_args():
    """Test spawn_in_thread with no arguments"""
    loop = EventLoop()

    def simple_work():
        return 42

    async def main():
        handle = await spawn_in_thread(simple_work)
        result = await handle.join()
        assert result == 42

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.0 <= actual <= 0.15


def test_spawn_in_thread_return_none():
    """Test spawn_in_thread when function returns None"""
    loop = EventLoop()

    executed = []

    def work_no_return():
        executed.append(True)
        time.sleep(0.05)

    async def main():
        handle = await spawn_in_thread(work_no_return)
        result = await handle.join()
        assert result is None
        assert executed == [True]

    actual = timeit(lambda: loop.run_until_complete(main(), join=True), number=1)
    assert 0.04 <= actual <= 0.2  # ~0.05s sleep
