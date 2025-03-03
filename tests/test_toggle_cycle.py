import logging
from collections.abc import AsyncGenerator
from typing import TypeVar, Union

from flowno import FlowHDL, Stream, node
from flowno.core.flow.flow import TerminateLimitReached
from flowno.core.node_base import NodePlaceholder
from flowno.core.types import Generation
from pytest import raises

logger = logging.getLogger(__name__)


T = TypeVar("T")


@node
async def StreamOutList(input: Union[list[str], None] = None):
    if input is None:
        input = ["a", "b"]
    for word in input:
        yield word


@node(stream_in=["stream"])
async def Upcase(stream: Stream[str]):
    async for word in stream:
        yield word.upper()


@node(stream_in=["stream"])
async def ReverseStream(stream: Stream[T]) -> list[T]:
    accumulator: list[T] = []
    async for word in stream:
        accumulator.insert(0, word)
    return accumulator


# passing
def test_streaming_cycle1_0():
    with FlowHDL() as f:
        f.streamed = StreamOutList(f.reverse)
        f.upcase = Upcase(f.streamed)
        f.reverse = ReverseStream(f.upcase)
    assert not isinstance(f.reverse, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.reverse: (0,)})
    assert f.reverse.get_data() == (["B", "A"],)


# passing
def test_streaming_cycle1_1():
    with FlowHDL() as f:
        f.streamed = StreamOutList(f.reverse)
        f.upcase = Upcase(f.streamed)
        f.reverse = ReverseStream(f.upcase)
    assert not isinstance(f.reverse, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.reverse: (1,)})
    assert f.reverse.get_data() == (["A", "B"],)


# passing
def test_streaming_cycle1_2():
    with FlowHDL() as f:
        f.streamed = StreamOutList(f.reverse)
        f.upcase = Upcase(f.streamed)
        f.reverse = ReverseStream(f.upcase)
    assert not isinstance(f.reverse, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.reverse: (2,)})
    assert f.reverse.get_data() == (["B", "A"],)


# passing
def test_streaming_cycle1_3():
    with FlowHDL() as f:
        f.streamed = StreamOutList(f.reverse)
        f.upcase = Upcase(f.streamed)
        f.reverse = ReverseStream(f.upcase)
    assert not isinstance(f.reverse, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.reverse: (3,)})
    assert f.reverse.get_data() == (["A", "B"],)


@node(stream_in=["stream"])
async def JoinReverse(stream: Stream[str]) -> str:
    accumulator = ""
    async for word in stream:
        accumulator = word + " " + accumulator
    return accumulator.strip()


@node
async def ListOfWords(input: str) -> list[str]:
    return input.split()


def get_data_for_flow2_stopping_at_chars_generation_(generation: Generation):
    with FlowHDL() as f:
        f.streamed = StreamOutList(f.chars)
        f.joined = JoinReverse(f.streamed)
        f.chars = ListOfWords(f.joined)
    assert not isinstance(f.chars, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.chars: generation})
    return f.chars.get_data()


# passing
def test_streaming_cycle2_0():
    assert get_data_for_flow2_stopping_at_chars_generation_((0,)) == (["b", "a"],)


# failing
def test_streaming_cycle2_1():
    assert get_data_for_flow2_stopping_at_chars_generation_((1,)) == (["a", "b"],)


# failing
def test_streaming_cycle2_2():
    assert get_data_for_flow2_stopping_at_chars_generation_((2,)) == (["b", "a"],)


# passing
def test_streaming_cycle2_3():
    assert get_data_for_flow2_stopping_at_chars_generation_((3,)) == (["a", "b"],)


# passing
def test_streaming_cycle2_4():
    assert get_data_for_flow2_stopping_at_chars_generation_((4,)) == (["b", "a"],)


# failing
def test_streaming_cycle2_5():
    assert get_data_for_flow2_stopping_at_chars_generation_((5,)) == (["a", "b"],)
