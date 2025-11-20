"""Test AsyncMapQueue implementation."""

from flowno.core.event_loop.event_loop import EventLoop
from flowno.core.event_loop.queues import AsyncMapQueue, QueueClosedError


def test_basic_put_get():
    """Test basic put and get operations."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("key1", "reason1"))
        assert len(amq) == 1

        key, causes = await amq.get()
        assert key == "key1"
        assert causes == ["reason1"]
        assert len(amq) == 0

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_basic_put_get")


def test_duplicate_key_accumulates_causes():
    """Test that putting the same key multiple times accumulates causes."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("key1", "reason1"))
        await amq.put(("key1", "reason2"))
        await amq.put(("key1", "reason3"))

        # Should only have one key in queue
        assert len(amq) == 1

        key, causes = await amq.get()
        assert key == "key1"
        assert causes == ["reason1", "reason2", "reason3"]
        assert len(amq) == 0

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_duplicate_key_accumulates_causes")


def test_fifo_order_on_first_insertion():
    """Test that keys are dequeued in FIFO order based on first insertion."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("key1", "reason1"))
        await amq.put(("key2", "reason2"))
        await amq.put(("key3", "reason3"))
        await amq.put(("key1", "reason4"))  # Append to existing key1
        await amq.put(("key2", "reason5"))  # Append to existing key2

        # Should have 3 unique keys
        assert len(amq) == 3

        # Get in FIFO order
        key, causes = await amq.get()
        assert key == "key1"
        assert causes == ["reason1", "reason4"]

        key, causes = await amq.get()
        assert key == "key2"
        assert causes == ["reason2", "reason5"]

        key, causes = await amq.get()
        assert key == "key3"
        assert causes == ["reason3"]

        assert len(amq) == 0

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_fifo_order_on_first_insertion")


def test_peek():
    """Test peek returns next item without removing it."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("key1", "reason1"))
        await amq.put(("key2", "reason2"))

        # Peek at first item
        key, causes = await amq.peek()
        assert key == "key1"
        assert causes == ["reason1"]
        assert len(amq) == 2  # Not removed

        # Peek again
        key, causes = await amq.peek()
        assert key == "key1"
        assert len(amq) == 2

        # Now get it
        key, causes = await amq.get()
        assert key == "key1"
        assert len(amq) == 1

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_peek")


def test_close():
    """Test closing the queue."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("key1", "reason1"))
        assert not amq.is_closed()

        await amq.close()
        assert amq.is_closed()

        # Can still get existing items
        key, causes = await amq.get()
        assert key == "key1"

        # But can't put new items
        try:
            await amq.put(("key2", "reason2"))
            assert False, "Should have raised QueueClosedError"
        except QueueClosedError:
            pass

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_close")


def test_complex_scenario():
    """Test complex scenario with interleaved puts."""
    async def test():
        amq = AsyncMapQueue()

        # Simulate node enqueueing
        await amq.put(("node1", "completed generation (0,)"))
        await amq.put(("node2", "barrier released"))
        await amq.put(("node3", "stalled request"))
        await amq.put(("node1", "barrier released"))
        await amq.put(("node2", "output node enqueued"))
        await amq.put(("node1", "ready to continue"))

        assert len(amq) == 3

        # Process in order
        key, causes = await amq.get()
        assert key == "node1"
        assert causes == ["completed generation (0,)", "barrier released", "ready to continue"]

        key, causes = await amq.get()
        assert key == "node2"
        assert causes == ["barrier released", "output node enqueued"]

        key, causes = await amq.get()
        assert key == "node3"
        assert causes == ["stalled request"]

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_complex_scenario")


def test_repr():
    """Test string representation."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("key1", "reason1"))
        await amq.put(("key1", "reason2"))

        repr_str = repr(amq)
        assert "AsyncMapQueue" in repr_str
        assert "key1" in repr_str

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_repr")


if __name__ == "__main__":
    test_basic_put_get()
    test_duplicate_key_accumulates_causes()
    test_fifo_order_on_first_insertion()
    test_peek()
    test_close()
    test_complex_scenario()
    test_repr()
    print("\n✅ All AsyncMapQueue tests passed!")
