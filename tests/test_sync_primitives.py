"""
Comprehensive tests for Flowno synchronization primitives: Event, Lock, Condition.

These tests verify:
- Basic functionality (set, wait, acquire, release, notify)
- Concurrent behavior (multiple waiters, FIFO ordering)
- Fast paths (already-set events, unlocked locks)
- Atomicity guarantees (condition wait releases lock atomically)
- Integration scenarios (multiple primitives together)


DANGER: THIS FILE WAS GENRERATED ENTIRELY USING CLAUDE CODE.
"""

import pytest
from flowno import Event, Lock, Condition, EventLoop
from flowno.core.event_loop.primitives import spawn


@pytest.fixture
def event_loop():
    """Provide a fresh EventLoop for each test"""
    return EventLoop()


# ============================================================================
# Event Tests (4 tests)
# ============================================================================

def test_event_basic_set_wait(event_loop):
    """Test that event.wait() blocks until event.set() is called"""

    async def main():
        event = Event()
        results = []

        async def waiter():
            results.append("waiting")
            await event.wait()
            results.append("done")

        task = await spawn(waiter())
        results.append("setting")
        await event.set()
        await task.join()

        return results

    result = event_loop.run_until_complete(main(), join=True)
    assert result == ["waiting", "setting", "done"]


def test_event_already_set(event_loop):
    """Test that wait() returns immediately if event is already set"""

    async def main():
        event = Event()
        await event.set()

        # This should return immediately
        await event.wait()
        await event.wait()  # Multiple waits on set event

        return "success"

    result = event_loop.run_until_complete(main(), join=True)
    assert result == "success"


def test_event_multiple_waiters(event_loop):
    """Test that event.set() wakes all waiting tasks"""

    async def main():
        event = Event()
        results = []

        async def waiter(name):
            await event.wait()
            results.append(name)

        # Spawn multiple waiters
        w1 = await spawn(waiter("w1"))
        w2 = await spawn(waiter("w2"))
        w3 = await spawn(waiter("w3"))

        # Set event - should wake all
        await event.set()

        await w1.join()
        await w2.join()
        await w3.join()

        return sorted(results)

    result = event_loop.run_until_complete(main(), join=True)
    assert result == ["w1", "w2", "w3"]


def test_event_is_set(event_loop):
    """Test that is_set() reflects event state correctly"""

    async def main():
        event = Event()

        assert not event.is_set()
        await event.set()
        assert event.is_set()

        # After set, remains set
        await event.wait()
        assert event.is_set()

        return "success"

    result = event_loop.run_until_complete(main(), join=True)
    assert result == "success"


# ============================================================================
# Lock Tests (4 tests)
# ============================================================================

def test_lock_basic_acquire_release(event_loop):
    """Test basic lock acquire and release"""

    async def main():
        lock = Lock()

        assert not lock.is_locked()

        await lock.acquire()
        assert lock.is_locked()

        await lock.release()
        assert not lock.is_locked()

        return "success"

    result = event_loop.run_until_complete(main(), join=True)
    assert result == "success"


def test_lock_mutual_exclusion(event_loop):
    """Test that only one task can hold the lock at a time"""

    async def main():
        lock = Lock()
        counter = [0]
        execution_order = []

        async def critical_section(name):
            await lock.acquire()
            try:
                execution_order.append(f"{name}_enter")
                # Simulate work - yield control
                current = counter[0]
                counter[0] = current + 1
                execution_order.append(f"{name}_exit")
            finally:
                await lock.release()

        # Spawn two tasks
        t1 = await spawn(critical_section("t1"))
        t2 = await spawn(critical_section("t2"))

        await t1.join()
        await t2.join()

        return counter[0], execution_order

    count, order = event_loop.run_until_complete(main(), join=True)
    assert count == 2
    # Verify no interleaving (t1 enter/exit before t2, or vice versa)
    assert (order == ["t1_enter", "t1_exit", "t2_enter", "t2_exit"] or
            order == ["t2_enter", "t2_exit", "t1_enter", "t1_exit"])


def test_lock_fifo_ordering(event_loop):
    """Test that lock waiters are served in FIFO order"""

    async def main():
        lock = Lock()
        order = []

        async def waiter(name):
            await lock.acquire()
            order.append(name)
            await lock.release()

        # Pre-acquire lock
        await lock.acquire()

        # Spawn multiple waiters (they'll block in order)
        w1 = await spawn(waiter("w1"))
        w2 = await spawn(waiter("w2"))
        w3 = await spawn(waiter("w3"))

        # Release - w1 should acquire next
        await lock.release()

        await w1.join()
        await w2.join()
        await w3.join()

        return order

    result = event_loop.run_until_complete(main(), join=True)
    assert result == ["w1", "w2", "w3"]


def test_lock_fast_path_unlocked(event_loop):
    """Test that acquire() succeeds immediately when lock is unlocked"""

    async def main():
        lock = Lock()

        # Should acquire immediately (fast path)
        await lock.acquire()
        assert lock.is_locked()
        await lock.release()

        # Acquire again
        await lock.acquire()
        await lock.release()

        return "success"

    result = event_loop.run_until_complete(main(), join=True)
    assert result == "success"


# ============================================================================
# Condition Tests (4 tests)
# ============================================================================

def test_condition_basic_wait_notify(event_loop):
    """Test basic condition wait and notify"""

    async def main():
        lock = Lock()
        condition = Condition(lock)
        results = []

        async def waiter():
            await lock.acquire()
            results.append("waiting")
            await condition.wait()
            # Lock is reacquired here
            results.append("notified")
            await lock.release()

        async def notifier():
            await lock.acquire()
            results.append("notifying")
            await condition.notify()
            await lock.release()

        w = await spawn(waiter())
        n = await spawn(notifier())

        await w.join()
        await n.join()

        return results

    result = event_loop.run_until_complete(main(), join=True)
    assert "waiting" in result
    assert "notifying" in result
    assert "notified" in result


def test_condition_notify_all(event_loop):
    """Test that notify_all() wakes all waiting tasks"""

    async def main():
        lock = Lock()
        condition = Condition(lock)
        results = []

        async def waiter(name):
            await lock.acquire()
            await condition.wait()
            results.append(name)
            await lock.release()

        async def notifier():
            await lock.acquire()
            await condition.notify_all()
            await lock.release()

        # Spawn multiple waiters
        w1 = await spawn(waiter("w1"))
        w2 = await spawn(waiter("w2"))
        w3 = await spawn(waiter("w3"))

        # Notify all
        n = await spawn(notifier())

        await w1.join()
        await w2.join()
        await w3.join()
        await n.join()

        return sorted(results)

    result = event_loop.run_until_complete(main(), join=True)
    assert result == ["w1", "w2", "w3"]


def test_condition_producer_consumer(event_loop):
    """Test producer-consumer pattern using condition variable"""

    async def main():
        lock = Lock()
        condition = Condition(lock)
        buffer = []

        async def producer():
            await lock.acquire()
            buffer.append("item")
            await condition.notify()
            await lock.release()

        async def consumer():
            await lock.acquire()
            while not buffer:
                await condition.wait()
            item = buffer.pop()
            await lock.release()
            return item

        c = await spawn(consumer())
        p = await spawn(producer())

        await p.join()
        result = await c.join()

        return result

    result = event_loop.run_until_complete(main(), join=True)
    assert result == "item"


def test_condition_wait_releases_lock(event_loop):
    """Test that condition.wait() atomically releases the lock"""

    async def main():
        lock = Lock()
        condition = Condition(lock)
        results = []

        async def waiter():
            await lock.acquire()
            results.append("waiter_has_lock")
            await condition.wait()
            results.append("waiter_reacquired")
            await lock.release()

        async def acquirer():
            await lock.acquire()
            results.append("acquirer_has_lock")
            await condition.notify()
            await lock.release()

        w = await spawn(waiter())
        a = await spawn(acquirer())

        await w.join()
        await a.join()

        return results

    result = event_loop.run_until_complete(main(), join=True)
    # Verify acquirer got lock after waiter called wait()
    assert result.index("waiter_has_lock") < result.index("acquirer_has_lock")
    assert result.index("acquirer_has_lock") < result.index("waiter_reacquired")


# ============================================================================
# Integration Tests (2 tests)
# ============================================================================

def test_event_lock_coordination(event_loop):
    """Test using Event and Lock together for coordination"""

    async def main():
        lock = Lock()
        event = Event()
        shared = [0]

        async def modifier():
            await lock.acquire()
            shared[0] = 42
            await lock.release()
            await event.set()

        async def reader():
            await event.wait()
            await lock.acquire()
            value = shared[0]
            await lock.release()
            return value

        m = await spawn(modifier())
        r = await spawn(reader())

        await m.join()
        result = await r.join()

        return result

    result = event_loop.run_until_complete(main(), join=True)
    assert result == 42


def test_all_primitives_coordination(event_loop):
    """Test complex coordination using Event, Lock, and Condition"""

    async def main():
        # Setup: Event signals initialization, Lock protects counter,
        # Condition signals when threshold reached
        init_event = Event()
        lock = Lock()
        condition = Condition(lock)
        counter = [0]
        threshold = 3

        async def incrementer(name):
            await init_event.wait()  # Wait for initialization

            await lock.acquire()
            counter[0] += 1
            if counter[0] >= threshold:
                await condition.notify_all()
            await lock.release()

        async def waiter_for_threshold():
            await lock.acquire()
            while counter[0] < threshold:
                await condition.wait()
            result = counter[0]
            await lock.release()
            return result

        # Spawn incrementers and threshold waiter
        i1 = await spawn(incrementer("i1"))
        i2 = await spawn(incrementer("i2"))
        i3 = await spawn(incrementer("i3"))
        w = await spawn(waiter_for_threshold())

        # Signal initialization
        await init_event.set()

        await i1.join()
        await i2.join()
        await i3.join()
        result = await w.join()

        return result

    result = event_loop.run_until_complete(main(), join=True)
    assert result == 3


# ============================================================================
# Event Timeout Tests (5 tests)
# ============================================================================

def test_event_wait_timeout_expires(event_loop):
    """Test that event.wait() with timeout returns False when timeout expires"""

    async def main():
        event = Event()

        # Wait with a short timeout - should return False since event is never set
        result = await event.wait(timeout=0.01)

        return result

    result = event_loop.run_until_complete(main(), join=True)
    assert result is False


def test_event_wait_timeout_event_set(event_loop):
    """Test that event.wait() with timeout returns True when event is set before timeout"""

    async def main():
        event = Event()
        results = []

        async def setter():
            await event.set()
            results.append("set")

        # Spawn setter which runs immediately
        s = await spawn(setter())

        # Wait with a long timeout - event will be set before timeout
        result = await event.wait(timeout=10.0)
        results.append(f"wait_result={result}")

        await s.join()
        return results

    result = event_loop.run_until_complete(main(), join=True)
    assert "set" in result
    assert "wait_result=True" in result


def test_event_wait_timeout_already_set(event_loop):
    """Test that wait(timeout) returns True immediately if event is already set"""

    async def main():
        event = Event()
        await event.set()

        # This should return True immediately (fast path)
        result = await event.wait(timeout=0.001)

        return result

    result = event_loop.run_until_complete(main(), join=True)
    assert result is True


def test_event_wait_no_timeout_returns_true(event_loop):
    """Test that wait() without timeout returns True when event is set"""

    async def main():
        event = Event()

        async def setter():
            await event.set()

        s = await spawn(setter())
        result = await event.wait()  # No timeout
        await s.join()

        return result

    result = event_loop.run_until_complete(main(), join=True)
    assert result is True


def test_event_wait_timeout_multiple_waiters(event_loop):
    """Test multiple waiters with different timeouts"""

    async def main():
        event = Event()
        results = []

        async def waiter_short():
            result = await event.wait(timeout=0.01)
            results.append(f"short={result}")

        async def waiter_long():
            result = await event.wait(timeout=10.0)
            results.append(f"long={result}")

        async def setter():
            # Use a small delay (via multiple spawn/joins) before setting
            # This gives the short waiter time to timeout
            from flowno import sleep
            await sleep(0.05)
            await event.set()
            results.append("set")

        # Short timeout waiter - will timeout
        ws = await spawn(waiter_short())
        # Long timeout waiter - will be woken by event
        wl = await spawn(waiter_long())
        # Setter - sets event after short timeout expires
        s = await spawn(setter())

        await ws.join()
        await wl.join()
        await s.join()

        return results

    result = event_loop.run_until_complete(main(), join=True)
    assert "short=False" in result  # Timed out
    assert "long=True" in result    # Event was set
    assert "set" in result
