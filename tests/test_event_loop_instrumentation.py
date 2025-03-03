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
