"""Test AsyncMapQueue behavior when reinserting a previously removed key."""

from flowno.core.event_loop.event_loop import EventLoop
from flowno.core.event_loop.queues import AsyncMapQueue


def test_reinsert_goes_to_back():
    """Test that a key removed and re-added goes to the BACK of the queue."""
    async def test():
        amq = AsyncMapQueue()

        # Add three keys
        await amq.put(("key1", "first insertion"))
        await amq.put(("key2", "reason2"))
        await amq.put(("key3", "reason3"))

        assert len(amq) == 3

        # Get key1 (removes it completely)
        key, causes = await amq.get()
        assert key == "key1"
        assert causes == ["first insertion"]
        assert len(amq) == 2

        # Re-add key1 - should go to BACK of queue
        await amq.put(("key1", "second insertion"))
        assert len(amq) == 3

        # Now get should return: key2, key3, THEN key1
        key, causes = await amq.get()
        assert key == "key2", f"Expected key2, got {key}"
        assert causes == ["reason2"]

        key, causes = await amq.get()
        assert key == "key3", f"Expected key3, got {key}"
        assert causes == ["reason3"]

        key, causes = await amq.get()
        assert key == "key1", f"Expected key1, got {key}"
        assert causes == ["second insertion"], f"Expected ['second insertion'], got {causes}"

        assert len(amq) == 0

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_reinsert_goes_to_back")


def test_multiple_reinsertions():
    """Test multiple get/put cycles maintain correct ordering."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("A", "A1"))
        await amq.put(("B", "B1"))
        await amq.put(("C", "C1"))

        # Get A, reinsert A
        key, _ = await amq.get()
        assert key == "A"
        await amq.put(("A", "A2"))

        # Get B, reinsert B
        key, _ = await amq.get()
        assert key == "B"
        await amq.put(("B", "B2"))

        # Now order should be: C, A, B
        key, causes = await amq.get()
        assert key == "C"
        assert causes == ["C1"]

        key, causes = await amq.get()
        assert key == "A"
        assert causes == ["A2"]

        key, causes = await amq.get()
        assert key == "B"
        assert causes == ["B2"]

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_multiple_reinsertions")


def test_reinsert_vs_append():
    """Test the difference between reinserting (after get) and appending (without get)."""
    async def test():
        amq = AsyncMapQueue()

        await amq.put(("X", "X1"))
        await amq.put(("Y", "Y1"))

        # Append to X without getting it - should stay at front
        await amq.put(("X", "X2"))

        key, causes = await amq.get()
        assert key == "X", "X should still be first"
        assert causes == ["X1", "X2"], "X should have both causes"

        # Now Y is next
        key, causes = await amq.get()
        assert key == "Y"

        # Add Z, then reinsert X - X should go to back (after Z)
        await amq.put(("Z", "Z1"))
        await amq.put(("X", "X3"))

        # Z should come before X since Z was inserted first
        key, causes = await amq.get()
        assert key == "Z", "Z should come before re-inserted X"

        key, causes = await amq.get()
        assert key == "X", "X should be last"
        assert causes == ["X3"], "X should only have new cause, not old ones"

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_reinsert_vs_append")


if __name__ == "__main__":
    test_reinsert_goes_to_back()
    test_multiple_reinsertions()
    test_reinsert_vs_append()
    print("\n✅ All AsyncMapQueue reinsertion tests passed!")
