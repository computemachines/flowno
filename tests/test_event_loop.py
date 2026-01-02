from time import time
from timeit import timeit

import pytest
from flowno import EventLoop, sleep, spawn, AsyncQueue
from flowno.core.event_loop.primitives import azip
from flowno.core.event_loop.queues import QueueClosedError, AsyncSetQueue
from flowno.core.event_loop.synchronization import CountdownLatch
from flowno.io.http_client import HttpClient, OkStreamingResponse
from flowno.utilities.logging import log_async

# @pytest.fixture(autouse=True)
# def set_env():
#     os.environ["NOODLIUM_LOG_LEVEL"] = "DEBUG"


def test_braindead():
    loop = EventLoop()

    async def braindead():
        print("Hello")

    loop.run_until_complete(braindead())


def test_sleep():
    loop = EventLoop()

    async def sleep_test():
        print("Sleeping")
        _ = await sleep(1)
        print("Done sleeping")

    actual = timeit(lambda: loop.run_until_complete(sleep_test()), number=1)
    assert 1 <= actual <= 1.1


def test_spawn():
    loop = EventLoop()

    async def sleep_test():
        print("Sleeping")
        _ = await sleep(1)
        print("Done sleeping")
        return "hello"

    async def spawn_test():
        print("Spawning")
        task_handle = await spawn(sleep_test())
        print("Done spawning")
        value = await task_handle.join()
        assert value == "hello"
        print("Joined")

    actual = timeit(lambda: loop.run_until_complete(spawn_test(), join=True), number=1)
    assert 1 <= actual <= 1.1


def test_should_fail():
    loop = EventLoop()

    async def error():
        raise ValueError("This is an error")

    with pytest.raises(ValueError):
        _ = loop.run_until_complete(error(), join=True)


def test_queue():
    loop = EventLoop()

    async def queue_test():
        q = AsyncQueue[int]()
        await q.put(1)
        await q.put(2)
        await q.put(3)
        assert await q.get() == 1
        assert await q.get() == 2
        assert await q.get() == 3

    loop.run_until_complete(queue_test(), join=True)


def test_queue_spsc():
    @log_async
    async def producer(q: AsyncQueue[int]):
        for i in range(10):
            await q.put(i)
            _ = await sleep(0.1)

    @log_async
    async def consumer(q: AsyncQueue[int]):
        total = 0
        for i in range(10):
            value = await q.get()
            total += value
            print(value)
            assert value == i
        return total

    @log_async
    async def main():
        q = AsyncQueue[int]()
        t1 = await spawn(producer(q))
        t2 = await spawn(consumer(q))
        await t1.join()
        return await t2.join()

    loop = EventLoop()
    total = loop.run_until_complete(main(), join=True)
    assert total == 45


def test_queue_mpsc():
    async def producer(q: AsyncQueue[int]):
        for i in range(10):
            await q.put(i)
            _ = await sleep(0.1)

    async def consumer(q: AsyncQueue[int]):
        total = 0
        async for value in q:
            total += value
        return total

    async def main():
        q = AsyncQueue[int]()
        t1 = await spawn(producer(q))
        t2 = await spawn(producer(q))
        t3 = await spawn(consumer(q))
        await t1.join()
        await t2.join()
        await q.close()
        return await t3.join()

    loop = EventLoop()
    start_time = time()
    total = loop.run_until_complete(main(), join=True)
    duration = time() - start_time
    assert 1 <= duration <= 1.3
    assert total == 45 * 2


def test_queue_mpmc():
    @log_async
    async def producer(q: AsyncQueue[int]):
        for i in range(10):
            await q.put(i)
            _ = await sleep(0.1)

    @log_async
    async def consumer(q: AsyncQueue[int]):
        total = 0
        async for value in q:
            total += value
        return total

    @log_async
    async def main():
        q = AsyncQueue[int]()
        t1 = await spawn(producer(q))
        t3 = await spawn(consumer(q))
        t4 = await spawn(consumer(q))
        await t1.join()
        await q.close()
        total1 = await t3.join()
        total2 = await t4.join()
        assert total1 != 0
        assert total2 != 0
        return total1 + total2

    loop = EventLoop()
    start_time = time()
    total = loop.run_until_complete(main(), join=True)
    duration = time() - start_time
    assert 1 <= duration <= 1.3
    assert total == 45


def test_queue_close_wakes_blocked_getter():
    """Test that closing a queue wakes up tasks blocked on get() with QueueClosedError."""
    loop = EventLoop()
    
    async def waiter(q: AsyncQueue[str]):
        """Task that blocks on get() from empty queue."""
        try:
            await q.get()
            return "ERROR: Should have raised QueueClosedError"
        except QueueClosedError:
            return "SUCCESS: QueueClosedError caught"
    
    async def main():
        q = AsyncQueue[str]()
        # Start waiter task that will block on empty queue
        waiter_task = await spawn(waiter(q))
        # Give waiter time to block
        await sleep(0.05)
        # Close the queue, which should wake up the waiter
        await q.close()
        # Get result from waiter
        result = await waiter_task.join()
        return result
    
    result = loop.run_until_complete(main(), join=True)
    assert result == "SUCCESS: QueueClosedError caught"


def test_queue_close_wakes_blocked_putter():
    """Test that closing a queue wakes up tasks blocked on put() with QueueClosedError."""
    loop = EventLoop()
    
    async def putter(q: AsyncQueue[str]):
        """Task that blocks on put() to full queue."""
        try:
            # Try to put into full queue - will block
            await q.put("item")
            return "ERROR: Should have raised QueueClosedError"
        except QueueClosedError:
            return "SUCCESS: QueueClosedError caught"
    
    async def main():
        q = AsyncQueue[str](maxsize=1)
        # Fill the queue
        await q.put("filling")
        # Start putter task that will block on full queue
        putter_task = await spawn(putter(q))
        # Give putter time to block
        await sleep(0.05)
        # Close the queue, which should wake up the putter
        await q.close()
        # Get result from putter
        result = await putter_task.join()
        return result
    
    result = loop.run_until_complete(main(), join=True)
    assert result == "SUCCESS: QueueClosedError caught"


def test_httpclient_200():
    loop = EventLoop()

    async def main():
        client = HttpClient()

        response = await client.stream_get("http://httpbin.org/stream/3")
        assert response.is_ok

        chunk_count = 0
        if isinstance(response, OkStreamingResponse):
            async for chunk in response.body:
                chunk_count += 1


def test_countdown_latch():
    """
    Test that a CountdownLatch with count=3 returns immediately from wait()
    once three count_down() calls have been made.
    """
    loop = EventLoop()

    async def latch_test():
        latch = CountdownLatch(3)
        # Simulate three countdown events.
        await latch.count_down()
        await latch.count_down()
        await latch.count_down()
        # Once count_down has been called three times, wait() should not block.
        start = time()
        await latch.wait()
        end = time()
        # Return the duration of wait(); it should be near zero.
        return end - start

    duration = loop.run_until_complete(latch_test(), join=True)
    # We allow a small margin (e.g. 0.1 seconds) to account for scheduling overhead.
    assert duration < 0.1, f"Latch waited too long: {duration:.3f} seconds"


def test_countdown_latch_spawn():
    log = []  # list to record ordering

    async def task1(latch: CountdownLatch):
        # Introduce a short delay so that task2 runs first.
        await sleep(0.1)
        log.append("task1: count_down")
        await latch.count_down()

    async def task2(latch: CountdownLatch):
        log.append("task2: count_down")
        await latch.count_down()

    async def task3(latch: CountdownLatch):
        log.append("task3: wait start")
        await latch.wait()
        log.append("task3: wait done")

    async def main():
        # Create a latch with count 2.
        latch = CountdownLatch(2)
        # Spawn two tasks that each count down the latch.
        t1 = await spawn(task1(latch))
        t2 = await spawn(task2(latch))
        t3 = await spawn(task3(latch))
        # Wait for the spawned tasks to complete.
        await t1.join()
        await t2.join()
        await t3.join()

    loop = EventLoop()
    loop.run_until_complete(main(), join=True)

    # Expected ordering:
    # 1. task2 runs immediately and calls count_down() ("task2: count_down")
    # 2. task1 runs after a 0.1 second delay ("task1: count_down")
    # 3. main prints "main: before wait", then awaits latch.wait() (which returns immediately),
    # 4. then main prints "main: after wait".
    expected = [
        "task2: count_down",
        "task3: wait start",
        "task1: count_down",
        "task3: wait done",
    ]
    assert log == expected, f"Expected log {expected} but got {log}"


def test_azip():
    async def arange(end: int | None = None):
        if end is None:
            i = 0
            while True:
                yield i
                i += 1
        for i in range(end):
            yield i

    async def main():
        zipped = azip(arange(), arange(3))
        zipped_iter = aiter(zipped)
        assert (0, 0) == await anext(zipped_iter)
        assert (1, 1) == await anext(zipped_iter)
        assert (2, 2) == await anext(zipped_iter)
        with pytest.raises(StopAsyncIteration):
            _ = await anext(zipped_iter)

    loop = EventLoop()
    loop.run_until_complete(main(), join=True)


def test_async_set_queue_put_nowait():
    loop = EventLoop()

    async def test():
        q = AsyncSetQueue[int]()
        
        # Test basic put_nowait
        assert q.put_nowait(1, loop) is True
        assert 1 in q
        assert len(q) == 1
        
        # Test deduplication
        assert q.put_nowait(1, loop) is False
        assert len(q) == 1
        
        # Test waking a waiter
        results = []
        
        async def waiter():
            val = await q.get()
            results.append(val)
            
        # Spawn a waiter. It should immediately get 1.
        _ = await spawn(waiter())
        await sleep(0.1)
        assert results == [1]
        assert len(q) == 0
        
        # Spawn another waiter. It should block.
        _ = await spawn(waiter())
        await sleep(0.1)
        assert len(results) == 1
        
        # Use put_nowait to wake the second waiter
        q.put_nowait(2, loop)
        
        # Give the waiter a chance to wake up and finish
        await sleep(0.1)
        assert 2 in results
        assert len(results) == 2
        assert len(q) == 0

    loop.run_until_complete(test(), join=True)
