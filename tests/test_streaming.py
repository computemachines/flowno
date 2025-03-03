import logging
from collections.abc import AsyncGenerator
from typing import Generic, TypeVar, Union, cast, final

import pytest
from flowno import FlowHDL, Stream, node
from flowno.core.mono_node import MonoNode0
from flowno.core.event_loop.instrumentation import EventLoopInstrument
from flowno.core.event_loop.instrumentation import (
    LogInstrument as EventLoopLogInstrument,
)
from flowno.core.event_loop.primitives import azip, sleep
from flowno.core.event_loop.queues import AsyncQueue
from flowno.core.flow.flow import Flow
from flowno.core.flow.flow import TerminateLimitReached
from flowno.core.flow.instrumentation import LogInstrument as FlowLogInstrument
from flowno.core.node_base import DraftNode, NodePlaceholder
from flowno.core.streaming_node import StreamingNode0
from pytest import raises
from typing_extensions import override

logger = logging.getLogger(__name__)

T = TypeVar("T")


@node
async def DummyConstant():
    return 42


@node(multiple_outputs=True)
async def DummyConstant2() -> AsyncGenerator[tuple[int], None]:
    yield (10,)


def test_braindead():
    flow = Flow()
    node = DummyConstant()._blank_finalized()
    flow.add_node(node)

    flow.run_until_complete()

    assert node.get_data() == (42,)


def test_stream_out_simple():
    flow = Flow()
    node = DummyConstant2()._blank_finalized()
    flow.add_node(node)

    flow.run_until_complete(terminate_on_node_error=True)

    assert node.get_data(0) is None
    assert node.get_data(1) == (10,)


@node
async def DummyWords(sentence: str):
    return sentence


@node
async def StreamingWords(sentence: str) -> AsyncGenerator[str, None]:
    for word in sentence.split():
        # _ = await sleep(0.1)
        print(f"yielding {word}")
        yield word
    print(f"finishing with {sentence}")
    raise StopAsyncIteration(sentence)


@node
async def UpcaseSentence(words: str) -> str:
    return words.upper()


def test_no_stream():
    with FlowHDL() as f:
        f.words = DummyWords("hello world")
        f.upcased = UpcaseSentence(f.words)

    f.run_until_complete(terminate_on_node_error=True)

    upcased = cast(UpcaseSentence, f.upcased)
    assert upcased.get_data() == ("HELLO WORLD",)


@node(stream_in=["words"])
async def UpcaseStreamReversedWords(words: Union[Stream[str], None] = None) -> str:
    accumulator = ""
    if words is not None:
        async for word in words:
            print(f"upcasing {word}")
            accumulator = word.upper() + " " + accumulator
    print(f"returning with {accumulator}")
    return accumulator.strip()


def test_minimum_run_levels():
    stream_node = UpcaseStreamReversedWords()
    assert stream_node._minimum_run_level == [1]  # pyright: ignore[reportPrivateUsage]

    simple_node = UpcaseSentence("hello world")
    assert simple_node._minimum_run_level == [0]  # pyright: ignore[reportPrivateUsage]


@final
class SingleQueueNoRepeatInstrument(EventLoopInstrument, Generic[T]):
    def __init__(self):
        self.active_queue = None
        self.last_get_item: Union[tuple[T], None] = None
        self.last_put_item: Union[tuple[T], None] = None

    @override
    def on_queue_get(self, queue: AsyncQueue[T], item: T, immediate: bool) -> None:
        if item is None:
            # ignore barrier queues
            return
        if self.active_queue is None:
            self.active_queue = queue

        assert self.active_queue is queue, "The only queue is the resolution queue"
        if self.last_get_item is not None:
            assert item is not self.last_get_item[0], "There should be no repeat queue gets"
        self.last_get_item = (item,)

    @override
    def on_queue_put(self, queue: "AsyncQueue[T]", item: T, immediate: bool) -> None:
        if item is None:
            return
        if self.active_queue is None:
            self.active_queue = queue

        assert self.active_queue is queue, "The only queue is the resolution queue"
        if self.last_put_item is not None:
            assert item is not self.last_put_item[0], "There should be no repeat queue puts"
        self.last_put_item = (item,)


def test_streaming():
    @node
    async def MyStreamingWords():
        for word in "hello world abc foo bar".split():
            yield word

    with FlowHDL() as f:
        f.words = MyStreamingWords()
        f.upcased = UpcaseStreamReversedWords(f.words)

    with SingleQueueNoRepeatInstrument():
        f.run_until_complete(terminate_on_node_error=True, stop_at_node_generation=(2,))

    upcased = cast(UpcaseStreamReversedWords, f.upcased)
    assert upcased.get_data(0) == ("BAR FOO ABC WORLD HELLO",)


def test_stream_ignored():
    with FlowHDL() as f:
        f.words = StreamingWords("hello world")
        f.upcased = UpcaseSentence(f.words)

    f.run_until_complete(terminate_on_node_error=True)

    upcased = cast(UpcaseSentence, f.upcased)
    assert upcased.get_data() == ("HELLO WORLD",)


@node
async def Counter():
    for i in range(4):
        yield i


@node(stream_in=["values"])
async def Sum(values: Stream[int]):
    accumulator = 0
    async for value in values:
        accumulator += value
        yield accumulator
    raise StopAsyncIteration(accumulator)


@node
async def Print(value: int):
    print(value)


@pytest.mark.skip("Rerunning a flow doesn't work anymore. I don't know if I should allow that.")
def test_simple_stream_in_out():
    with FlowHDL() as f:
        f.counter = Counter()
        f.sum = Sum(f.counter)

    f.run_until_complete(terminate_on_node_error=True, _debug_max_wait_time=10)


#    sum = cast(Sum, f.sum)
#    counter = cast(Counter, f.counter)
#    assert sum.get_data(0) is None
#    assert sum.get_data(1) == (0,)
#    assert counter.get_data(0) is None
#    assert counter.get_data(1) == (0,)
#
#    f._flow.unvisited.append(cast(ObjectNode, sum))  # pyright: ignore[reportPrivateUsage]
#    f.run_until_complete(terminate_on_node_error=True, _debug_max_wait_time=10)
#
#    assert sum.get_data(0) is None
#    assert sum.get_data(1) == (1,)
#    assert counter.get_data(0) is None
#    assert counter.get_data(1) == (1,)
#
#    f._flow.unvisited.append(cast(ObjectNode, sum))  # pyright: ignore[reportPrivateUsage]
#    f.run_until_complete(terminate_on_node_error=True, _debug_max_wait_time=10)
#
#    assert sum.get_data(0) is None
#    assert sum.get_data(1) == (3,)
#    assert counter.get_data(0) is None
#    assert counter.get_data(1) == (2,)
#
#    f._flow.unvisited.append(cast(ObjectNode, sum))  # pyright: ignore[reportPrivateUsage]
#    f.run_until_complete(terminate_on_node_error=True, _debug_max_wait_time=10)
#
#    assert sum.get_data(0) is None
#    assert sum.get_data(1) == (6,)
#    assert counter.get_data(0) is None
#    assert counter.get_data(1) == (3,)


def test_stream_one_full_generation():
    with FlowHDL() as f:
        f.counter = Counter()
        f.sum = Sum(f.counter)
        f.print = Print(f.counter)

    f.run_until_complete(terminate_on_node_error=True)


@node
async def ImmediateTerminateStream():
    if 1 == 1:
        yield "goodbye"
    raise StopAsyncIteration("hello")


@node
async def Identity(value: T) -> T:
    return value


def test_immediate_terminate():
    with FlowHDL() as f:
        f.counter = ImmediateTerminateStream()
        f.ident = Identity(f.counter)

    f.run_until_complete(terminate_on_node_error=True)

    ident = cast(Identity, f.ident)
    assert ident.get_data() == ("hello",)


@node
async def OnePartStream():
    yield "partial"
    raise StopAsyncIteration("full")


def test_short_stream():
    with FlowHDL() as f:
        f.counter = OnePartStream()
        f.ident = Identity(f.counter)
        f.ident2 = Identity(f.counter)

    f.run_until_complete(terminate_on_node_error=True)

    ident = cast(Identity, f.ident)
    assert ident.get_data() == ("full",)


@node
async def ShortCounter():
    yield 10


def test_short_stream_one_full_generation():
    with FlowHDL() as f:
        f.counter = ShortCounter()
        f.sum = Sum(f.counter)
        f.print = Print(f.counter)

    f.run_until_complete(terminate_on_node_error=True)


@node
async def Words(input: Union[list[str], None] = None) -> AsyncGenerator[str, None]:
    if input is None:
        print("Words: input is None")
        input = ["hello", "world"]
    else:
        print(f"Words: input is {input}")
    for word in input:
        # break
        # _ = await sleep(0.1)
        print(f"Words: yielding {word}")
        yield word


@node(stream_in=["words"])
async def Upcase(words: Stream[str]) -> AsyncGenerator[str, None]:
    print("upcasing")
    async for word in words:
        print(f"upcasing {word}")
        yield word.upper()


@node(stream_in=["words"])
async def ReverseSentence(words: Stream[str]) -> str:
    print(f"ReversingSentence: {words}")
    accumulator = ""
    async for word in words:
        print(f"ReversingSentence, taken from stream: {word}")
        accumulator = word + " " + accumulator
        logger.debug(f"ReverseSentence accumulator: {accumulator}")
    print(f"ReversingSentence: returning {accumulator.strip()}")
    return accumulator.strip()


@node
async def Listify(words: str) -> list[str]:
    print(f"Listify input: {words}")
    print(f"Listify output: {words.split()}")
    return words.split()


def test_streaming_in_and_out():
    with FlowHDL() as f:
        f.words = Words()
        f.upcase = Upcase(f.words)
        f.reverse = ReverseSentence(f.upcase)

    f.run_until_complete(terminate_on_node_error=True, _debug_max_wait_time=10)

    reversed = cast(ReverseSentence, f.reverse)
    assert reversed.get_data(0) == ("WORLD HELLO",)


def test_streaming_cycle():
    with FlowHDL() as f:
        f.words = Words(f.listify)
        f.upcase = Upcase(f.words)
        f.reverse = ReverseSentence(f.upcase)
        f.listify = Listify(f.reverse)

    with raises(TerminateLimitReached):
        # run two complete cycles
        f.run_until_complete(
            terminate_on_node_error=True, stop_at_node_generation={f.reverse: (1,)}, _debug_max_wait_time=10
        )

    reversed = cast(ReverseSentence, f.reverse)
    logger.debug(reversed.get_data(0))
    assert reversed.get_data(0) == ("HELLO WORLD",), "Should have reversed the words twice"


@node
class StatefulStream:
    counter: int = 0

    async def call(self):
        while self.counter < 3:
            yield "abc"
            self.counter += 1


@node(stream_in=["stream"])
async def StreamToList(stream: Stream[str]) -> list[str]:
    return [x async for x in stream]


def test_stateful_stream():
    with FlowHDL() as f:
        f.buffer = StatefulStream()
        f.list = StreamToList(f.buffer)

    f.run_until_complete()
    assert f.list.get_data() == (["abc", "abc", "abc"],)


@node(stream_in=["numbers"])
class StreamAccumulator:
    total: float = 0.0
    count: int = 0

    async def call(self, numbers: Stream[float]) -> tuple[float, int]:
        async for num in numbers:
            self.total += num
            self.count += 1
        return (self.total, self.count)


@node
async def NumberStream():
    for x in [1.0, 2.0, 3.0]:
        yield x


def test_stateful_stream_in():
    with FlowHDL() as f:
        f.numbers = NumberStream()
        f.accumulator = StreamAccumulator(f.numbers)

    f.run_until_complete()

    acc = cast(StreamAccumulator, f.accumulator)
    assert acc.get_data() == ((6.0, 3),), "Should have accumulated all numbers"
    assert acc.total == 6.0, "State should persist"
    assert acc.count == 3, "Should have counted all items"


@node
async def Range(start: int, end: int):
    # Print a message so you can see when the node is run (optional)
    print(f"Range started: {start}..{end}")
    # Use a short sleep so tests do not take too long
    for i in range(start, end):
        await sleep(0.1)
        yield i


@node(stream_in=["left", "right"])
async def AddPiecewise(left: Stream[int], right: Stream[int]):
    # azip streams; for each pair, yield the sum
    async for l_item, r_item in azip(left, right):
        print(f"Adding {l_item} + {r_item}")
        yield l_item + r_item


@node(stream_in=["stream"])
async def Sum(stream: Stream[int]) -> int:
    total = 0
    async for item in stream:
        print(f"Sum received: {item}")
        await sleep(0.1)
        total += item
    print(f"Total: {total}")
    return total


def test_dummy_flow_with_log_instrumentation():
    """
    This test replicates the flow defined in dummy.py:
      - Two Range nodes produce streams (0,1,2 and 100,101,102)
      - AddPiecewise adds corresponding numbers (yielding 100, 102, 104)
      - Sum then accumulates these to yield 306.

    The flow is run inside two nested LogInstrument contexts.
    """
    with FlowHDL() as f:
        f.range_a = Range(0, 3)
        f.range_b = Range(100, 103)
        f.total = Sum(AddPiecewise(f.range_a, f.range_b))

    # Run the flow wrapped in two nested LogInstrument contexts.
    # (This shows that both instrumentation contexts are active during the run.)
    with FlowLogInstrument():
        with EventLoopLogInstrument():
            f.run_until_complete(terminate_on_node_error=True, _debug_max_wait_time=5)

    total = f.total.get_data()
    # The expected behavior:
    #   Range(0,3) yields: 0, 1, 2
    #   Range(100,103) yields: 100, 101, 102
    #   AddPiecewise yields: 0+100=100, 1+101=102, 2+102=104
    #   Sum adds these: 100 + 102 + 104 = 306
    assert total == (306,), f"Expected total (306,), got {total}"


def test_stream_chunking():
    @node
    async def FourNumbers():
        yield 0
        yield 1
        yield 2
        yield 3

        raise StopAsyncIteration("numbers done.")

    @node(stream_in=["numbers"])
    async def WaitForPair(numbers: Stream[int]):
        numbers_iter = aiter(numbers)

        first_left = await anext(numbers_iter)
        first_right = await anext(numbers_iter)
        yield (first_left, first_right)

        second_left = await anext(numbers_iter)
        second_right = await anext(numbers_iter)
        yield (second_left, second_right)

        with raises(StopAsyncIteration):
            _ = await anext(numbers_iter)

        raise StopAsyncIteration("chunking done.")

    @node(stream_in=["pairs"])
    async def ElementwiseAccumulate(pairs: Stream[tuple[int, int]]):
        total_left = 0
        total_right = 0

        pairs_iter = aiter(pairs)

        first_pair = await anext(pairs_iter)
        total_left += first_pair[0]
        total_right += first_pair[1]

        second_pair = await anext(pairs_iter)
        total_left += second_pair[0]
        total_right += second_pair[1]

        with raises(StopAsyncIteration):
            _ = await anext(pairs_iter)

        return (total_left, total_right)

    with FlowHDL() as f:
        f.numbers = FourNumbers()
        f.chunks = WaitForPair(f.numbers)
        f.total = ElementwiseAccumulate(f.chunks)

    with FlowLogInstrument():
        f.run_until_complete()

    assert f.total.get_data() == ((2, 4),)
