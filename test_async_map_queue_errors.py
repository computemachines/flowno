"""Test AsyncMapQueue error handling for invalid inputs."""

from flowno.core.event_loop.event_loop import EventLoop
from flowno.core.event_loop.queues import AsyncMapQueue


def test_put_non_tuple_raises_error():
    """Test that putting a non-tuple raises a clear error."""
    async def test():
        amq = AsyncMapQueue()

        # Try to put just a key without a reason tuple
        try:
            await amq.put("just_a_key")
            assert False, "Should have raised an error"
        except (ValueError, TypeError) as e:
            print(f"Got expected error: {type(e).__name__}: {e}")
            return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_put_non_tuple_raises_error")


def test_put_tuple_wrong_length_raises_error():
    """Test that putting a tuple with wrong number of elements raises an error."""
    async def test():
        amq = AsyncMapQueue()

        # Try with too many elements
        try:
            await amq.put(("key", "reason1", "reason2"))
            assert False, "Should have raised an error"
        except ValueError as e:
            print(f"Got expected error for too many values: {e}")

        # Try with too few elements
        try:
            await amq.put(("key_only",))
            assert False, "Should have raised an error"
        except ValueError as e:
            print(f"Got expected error for too few values: {e}")

        return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_put_tuple_wrong_length_raises_error")


def test_put_none_raises_error():
    """Test that putting None raises an error."""
    async def test():
        amq = AsyncMapQueue()

        try:
            await amq.put(None)
            assert False, "Should have raised an error"
        except (ValueError, TypeError) as e:
            print(f"Got expected error: {type(e).__name__}: {e}")
            return "pass"

    loop = EventLoop()
    result = loop.run_until_complete(test(), join=True)
    assert result == "pass"
    print("✓ test_put_none_raises_error")


if __name__ == "__main__":
    test_put_non_tuple_raises_error()
    test_put_tuple_wrong_length_raises_error()
    test_put_none_raises_error()
    print("\n✅ All AsyncMapQueue error handling tests passed!")
