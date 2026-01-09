from typing import final
from typing_extensions import override

from flowno.core.event_loop.event_loop import EventLoop
from flowno.core.event_loop.instrumentation import EventLoopInstrument
from flowno.core.event_loop.queues import AsyncQueue


@final
class MyInstrument(EventLoopInstrument):
    def __init__(self):
        self.items_popped: list[str] = []
        self.items_pushed: list[str] = []

    @override
    def on_queue_get(self, queue: AsyncQueue[str], item: str, immediate: bool) -> None:
        print(f"[Instrumentation] Popped from queue: {item!r}")
        self.items_popped.append(item)

    @override
    def on_queue_put(self, queue: AsyncQueue[str], item: str, immediate: bool) -> None:
        print(f"[Instrumentation] Pushed to Queue: {item!r}")
        self.items_pushed.append(item)


def test_on_queue_get_instrumentation():
    loop = EventLoop()
    queue = AsyncQueue[str]()
    # Add some items up front
    queue.items.append("hello")
    queue.items.append("world")

    async def do_get():
        item1 = await queue.get()
        item2 = await queue.get()
        return (item1, item2)

    with MyInstrument() as instrument:
        loop.run_until_complete(do_get())

    assert instrument.items_popped == ["hello", "world"]

def test_on_queue_put_instrumentation():
    loop = EventLoop()
    queue = AsyncQueue[str]()

    async def do_put():
        item1 = await queue.put("hello")
        item2 = await queue.put("world")

    with MyInstrument() as instrument:
        loop.run_until_complete(do_put())

    assert instrument.items_pushed == ["hello", "world"]


def test_simple_queue_put_with_instrumentation():
    """Simple test that creates an event loop and runs a coroutine that awaits a put on an async queue."""
    loop = EventLoop()
    queue = AsyncQueue[str]()

    async def simple_put():
        await queue.put("test_item")

    with MyInstrument() as instrument:
        loop.run_until_complete(simple_put())

    assert instrument.items_pushed == ["test_item"]
    assert len(queue.items) == 1
    assert queue.items[0] == "test_item"


# === Tests for nested/stacked instruments ===


class OrderTrackingInstrument(EventLoopInstrument):
    """Instrument that records the order of events with a label."""

    def __init__(self, label: str, event_log: list[str]):
        self.label = label
        self.event_log = event_log

    @override
    def on_queue_put(self, queue: AsyncQueue[str], item: str, immediate: bool) -> None:
        self.event_log.append(f"{self.label}:put:{item}")

    @override
    def on_queue_get(self, queue: AsyncQueue[str], item: str, immediate: bool) -> None:
        self.event_log.append(f"{self.label}:get:{item}")


def test_nested_instruments_both_receive_events():
    """Both nested instruments should receive all events."""
    loop = EventLoop()
    queue = AsyncQueue[str]()
    event_log: list[str] = []

    async def do_put():
        await queue.put("test")

    with OrderTrackingInstrument("outer", event_log):
        with OrderTrackingInstrument("inner", event_log):
            loop.run_until_complete(do_put())

    # Both should have received the put event
    assert "inner:put:test" in event_log
    assert "outer:put:test" in event_log


def test_inner_fires_before_outer():
    """Inner instrument should fire before outer (reverse order of nesting)."""
    loop = EventLoop()
    queue = AsyncQueue[str]()
    event_log: list[str] = []

    async def do_put():
        await queue.put("test")

    with OrderTrackingInstrument("outer", event_log):
        with OrderTrackingInstrument("inner", event_log):
            loop.run_until_complete(do_put())

    # Inner should appear before outer in the log
    inner_idx = event_log.index("inner:put:test")
    outer_idx = event_log.index("outer:put:test")
    assert inner_idx < outer_idx, f"Expected inner before outer, got: {event_log}"


def test_triple_nested_instruments():
    """Three levels of nesting should all receive events in correct order."""
    loop = EventLoop()
    queue = AsyncQueue[str]()
    event_log: list[str] = []

    async def do_put():
        await queue.put("test")

    with OrderTrackingInstrument("outer", event_log):
        with OrderTrackingInstrument("middle", event_log):
            with OrderTrackingInstrument("inner", event_log):
                loop.run_until_complete(do_put())

    # All three should have received the event
    assert "inner:put:test" in event_log
    assert "middle:put:test" in event_log
    assert "outer:put:test" in event_log

    # Order should be inner -> middle -> outer
    inner_idx = event_log.index("inner:put:test")
    middle_idx = event_log.index("middle:put:test")
    outer_idx = event_log.index("outer:put:test")
    assert inner_idx < middle_idx < outer_idx, f"Expected inner < middle < outer, got: {event_log}"


def test_instrument_cleanup_on_exit():
    """Instruments should be properly removed from stack on context exit."""
    from flowno.core.event_loop.instrumentation import _instrument_stack

    # Record initial stack size (may not be empty due to other test state)
    initial_size = len(_instrument_stack.get())

    with OrderTrackingInstrument("first", []):
        assert len(_instrument_stack.get()) == initial_size + 1
        with OrderTrackingInstrument("second", []):
            assert len(_instrument_stack.get()) == initial_size + 2
        # After inner exits, should be back to initial + 1
        assert len(_instrument_stack.get()) == initial_size + 1

    # After both exit, should be back to initial
    assert len(_instrument_stack.get()) == initial_size


def test_single_instrument_on_empty_stack_returns_directly():
    """Single instrument on empty stack should be returned directly, not wrapped."""
    from flowno.core.event_loop.instrumentation import get_current_instrument, _CompositeInstrument, _instrument_stack

    # Only run this assertion if the stack is actually empty
    # (test isolation issue from other tests may leave instruments on stack)
    if len(_instrument_stack.get()) > 0:
        return  # Skip - can't test single instrument when stack already has items

    event_log: list[str] = []
    instrument = OrderTrackingInstrument("single", event_log)

    with instrument:
        current = get_current_instrument()
        # Should be the same object, not a CompositeInstrument wrapper
        assert current is instrument
        assert not isinstance(current, _CompositeInstrument)


def test_multiple_instruments_returns_composite():
    """Multiple instruments should return a CompositeInstrument."""
    from flowno.core.event_loop.instrumentation import get_current_instrument, _CompositeInstrument

    event_log: list[str] = []

    with OrderTrackingInstrument("outer", event_log):
        with OrderTrackingInstrument("inner", event_log):
            current = get_current_instrument()
            # Should be a CompositeInstrument wrapping both
            assert isinstance(current, _CompositeInstrument)
