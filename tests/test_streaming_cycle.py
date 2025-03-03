import logging

import pytest
from flowno import FlowHDL, Stream, node
from flowno.core.flow.flow import TerminateLimitReached
from flowno.core.flow.instrumentation import LogInstrument as FlowLogInstrument
from flowno.core.node_base import NodePlaceholder
from pytest import mark, raises

logger = logging.getLogger(__name__)


counter = 0


@node
async def StreamOfChunks(chunks: list[str] | None = None):
    global counter
    if chunks is None:
        chunks = ["a", "b", "c"]
    for chunk in chunks:
        yield chunk
    counter += 1


@node(stream_in=["stream"])
async def JoinStreamIntoList(stream: Stream[str]):
    return [chunk async for chunk in stream]


def test_cycle_1():
    with FlowHDL() as flow:
        flow.stream = StreamOfChunks()
        flow.joined = JoinStreamIntoList(flow.stream)

    with raises(TerminateLimitReached):
        # stop when flow.joined reaches main-generation 0
        flow.run_until_complete(terminate_on_node_error=True, stop_at_node_generation={flow.joined: (0,)})

    assert not isinstance(flow.joined, NodePlaceholder)
    assert flow.joined.get_data(0) == (["a", "b", "c"],)


def test_cycle_stitch_nonstream_out_nonstream_in():
    log = []

    @node
    async def A(x=None):
        log.append("A")
        return x

    @node
    async def B(x):
        log.append("B")
        return x

    with FlowHDL() as f:
        f.node_A = A(f.node_B)
        f.node_B = B(f.node_A)

    with raises(TerminateLimitReached):
        with FlowLogInstrument():
            f.run_until_complete({f.node_A: (2,)})

    assert log == ["A", "B", "A", "B", "A"]


@pytest.mark.skip()
def test_cycle_stitch_nonstream_out_stream_in():
    # This case should error before running at all.
    # not going to test that yet
    pass


def test_cycle_stitch_stream_out_nonstream_in():
    log = []

    @node
    async def A(final_value=None):
        log.append("A")
        return final_value

    @node
    async def B(value):
        log.append("B0")
        yield "0 "
        log.append("B1")
        yield "1 "
        log.append("B2")
        yield "2 "
        log.append("B3")

    with FlowHDL() as f:
        f.node_A = A(f.node_B)
        f.node_B = B(f.node_A)

    with raises(TerminateLimitReached):
        with FlowLogInstrument():
            f.run_until_complete({f.node_A: (2,)})

    assert log == ["A", "B0", "B1", "B2", "B3", "A", "B0", "B1", "B2", "B3", "A"]


@mark.skip("not yet implemented")
def test_cycle_stitch_stream_out_stream_in_read_none():
    log = []

    @node(stream_in=["xs"])
    async def A(xs: Stream[str] | None = None):
        log.append("A.start")

        if xs is not None:
            pass

        log.append("A.done")
        return "hello"

    @node
    async def B(x):
        log.append("B0")
        yield "0 "
        log.append("B1")
        yield "1 "
        log.append("B2")
        yield "2 "
        log.append("B3")

    with FlowHDL() as f:
        f.node_A = A(f.node_B)
        f.node_B = B(f.node_A)

    with raises(TerminateLimitReached):
        with FlowLogInstrument():
            f.run_until_complete({f.node_A: (2,)})

    assert log == [
        "A.start",
        "A.done",
        "B0",
        "B1",
        "B2",
        "B3",
        "A.start",
        "A.done",
        "B0",
        "A.start",
        "A.done",
    ]


def test_cycle_stitch_stream_out_stream_in_read_all():
    log = []

    @node(stream_in=["xs"])
    async def A(xs: Stream[str] | None = None):
        log.append("A.start")

        if xs is not None:
            async for x in xs:
                log.append(f"A{x.strip()}")

        log.append("A.done")
        return "hello"

    @node
    async def B(x):
        log.append("B0")
        yield "0 "
        log.append("B1")
        yield "1 "
        log.append("B2")
        yield "2 "
        log.append("B3")

    with FlowHDL() as f:
        f.node_A = A(f.node_B)
        f.node_B = B(f.node_A)

    with raises(TerminateLimitReached):
        with FlowLogInstrument():
            f.run_until_complete({f.node_A: (2,)})

    assert log == [
        "A.start",
        "A.done",  # xs is none
        "B0",
        "A.start",
        "A0",
        "B1",
        "A1",
        "B2",
        "A2",
        "B3",
        "A.done",
        "B0",
        "A.start",
        "A0",
        "B1",
        "A1",
        "B2",
        "A2",
        "B3",
        "A.done",
    ]
