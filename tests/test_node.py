# pyright: basic
# pyright: reportPrivateUsage=false, reportUntypedFunctionDecorator=warning, reportUnknownMemberType=warning

from random import randint
from typing import TypeVar, cast
from typing_extensions import override

import pytest
from flowno import DraftNode, FlowHDL, node
from flowno.core.flow.flow import TerminateLimitReached
from flowno.core.flow.instrumentation import PrintInstrument
from flowno.core.node_base import MissingDefaultError
from flowno.core.types import Generation, InputPortIndex
from flowno.utilities.helpers import cmp_generation

T = TypeVar('T')

@node
async def randomize(max: int) -> int:
    return randint(0, max)


@node(multiple_outputs=True)
async def greet() -> tuple[str, str]:
    return "Hello", "World"


def test_node():
    node1 = randomize()
    node2 = greet()

    assert isinstance(node1, DraftNode)
    assert isinstance(node2, DraftNode)


class Increment(DraftNode[int, tuple[int]]):
    @override
    async def call(self, x: int) -> tuple[int]:
        return (x + 1,)


@node
class SimpleConstant:
    async def call(self) -> tuple[int]:
        return (42,)


def test_node_creation():
    # Create a node with 2 input ports
    node = SimpleConstant()._blank_finalized()

    node.push_data((42,))
    assert node.get_data() == (42,)

    node.push_data((43,), 1)
    assert node.get_data(0) == (42,)
    assert node.get_data(1) == (43,)
    assert node.get_data(2) is None

    node.push_data((44,), 0)
    assert node.get_data(0) == (44,)
    assert node.get_data(1) is None
    assert node.get_data(2) is None


@node
class MockNode:
    async def call(self, x: int) -> tuple[int]:
        return (x + 1,)


def make_mock_nodes(generation_a: Generation, generation_b: Generation, stream: bool):
    with FlowHDL() as f:
        f.node_a = MockNode(0)
        f.node_b = MockNode(f.node_a)

    if generation_a is not None:
        f.node_a._data[generation_a] = (42,)
    if generation_b is not None:
        f.node_b._data[generation_b] = (43,)

    if stream:
        f.node_b._input_ports[InputPortIndex(0)].minimum_run_level = 1

    return f.node_a, f.node_b


# node_b is normally ready when node_a.gen > node_b.gen
# node_b is not ready when node_a.gen <= node_b.gen
# this guidance is modified to accomodate the run level concept by clipping node_a.gen to input_b.min_run_level
@pytest.mark.parametrize(
    "stream, gen_a, gen_b, behavior",
    [
        (False, (0,), (0,), "deferred"),  # (0,) clipped to run level 0 is (0,) <= (0,) = gen_b
        (False, (1,), (0,), "evaluated"),  # (1,) clipped to run level 0 is (1,) > (0,) = gen_b
        (False, (1,), (1,), "deferred"),  # (1,) clipped to run level 1 is (1,) <= (1,) = gen_b
        (False, (0, 0), (0,), "deferred"),  # (0, 0) clipped to run level 0 is None <= (0,) = gen_b
        (False, (1, 0), (0,), "deferred"),  # (1, 0) clipped to run level 0 is (0,) <= (0,) = gen_b
        (False, (0, 1), (0,), "deferred"),  # (0, 1) clipped to run level 0 is None <= (0,) = gen_b
        (False, (0, 0), (0, 0), "deferred"),  # (0, 0) clipped to run level 0 is None <= (0, 0) = gen_b
        (False, (0, 0), (0, 1), "deferred"),  # (0, 0) clipped to run level 0 is None <= (0, 1) = gen_b
        (False, (0, 1), (0, 0), "deferred"),  # (0, 1) clipped to run level 0 is None <= (0, 0) = gen_b
        (False, (0, 1), (0, 1), "deferred"),  # (0, 1) clipped to run level 0 is None <= (0, 1) = gen_b
        (True, (0,), (0,), "deferred"),  # (0,) clipped to run level 1 is (0,) <= (0,) = gen_b
        (True, (1,), (0,), "evaluated"),  # (1,) clipped to run level 1 is (1,) > (0,) = gen_b
        (True, (1,), (1,), "deferred"),  # (1,) clipped to run level 1 is (1,) <= (1,) = gen_b
        (True, (0, 0), (0,), "deferred"),  # (0, 0) clipped to run level 1 is (0, 0) <= (0,) = gen_b
        (True, (1, 0), (0,), "evaluated"),  # (1, 0) clipped to run level 1 is (1, 0) > (0,) = gen_b
        (True, (0, 1), (0,), "deferred"),  # (0, 1) clipped to run level 1 is (0, 1) <= (0,) = gen_b
        (True, (0, 0), (0, 0), "deferred"),  # (0, 0) clipped to run level 1 is (0, 0) <= (0, 0) = gen_b
        (True, (0, 0), (0, 1), "deferred"),  # (0, 0) clipped to run level 1 is (0, 0) <= (0, 1) = gen_b
        (True, (0, 1), (0, 0), "evaluated"),  # (0, 1) clipped to run level 1 is (0, 1) > (0, 0) = gen_b
        (True, (0, 1), (0, 1), "deferred"),  # (0, 1) clipped to run level 1 is (0, 1) <= (0, 1) = gen_b
        (True, (0,), (0, 1), "evaluated"),  # (0,) clipped to run level 1 is (0,) > (0, 1) = gen_b
    ],
)
def test_resolution_logic_with_subgens(stream, gen_a, gen_b, behavior):
    node_a, node_b = make_mock_nodes(gen_a, gen_b, stream)
    assert node_a.generation == gen_a
    assert node_b.generation == gen_b

    if behavior != "deferred":
        assert cmp_generation(gen_a, gen_b) == 1

    # stale_inputs = node_b.get_inputs_with_le_generation()
    stale_inputs = node_b.get_inputs_with_le_generation_clipped_to_minimum_run_level()

    if behavior == "deferred":
        assert len(stale_inputs) == 1
        assert stale_inputs[0].connected_output.node == node_a
    else:
        assert len(stale_inputs) == 0


@node
async def StreamCounter():  # -> AsyncGenerator[str, None]:
    print("stream_counter")
    for i in ["a", "b", "c"]:
        print("yield", i)
        yield i


@node
async def TakeForeverDefault(x: T, self: object = None) -> T:
    print("take_forever")
    return x


@node
async def TakeForeverNoDefault(x: T, self: object) -> T:
    print("take_forever")
    return x

@node
async def Identity(x: T) -> T:
    return x

def test_identity_loop_no_default():

    with FlowHDL() as hdl:
        hdl.id_loop = Identity(hdl.id_loop)

    with pytest.raises(MissingDefaultError):
        hdl.run_until_complete(terminate_on_node_error=True, stop_at_node_generation=(2,))


def test_cycle_breaking_no_default():
    with FlowHDL() as hdl:
        hdl.forever = TakeForeverNoDefault(10, hdl.forever)

    with pytest.raises(MissingDefaultError):
        hdl.run_until_complete(terminate_on_node_error=True, stop_at_node_generation=(2,))


def test_streamed_data_generation():
    with FlowHDL() as hdl:
        hdl.counter = StreamCounter()
        hdl.forever = TakeForeverDefault(hdl.counter, hdl.forever)

    counter = cast(StreamCounter, hdl.counter)

    with PrintInstrument():
        with pytest.raises(TerminateLimitReached):
            hdl.run_until_complete(terminate_on_node_error=True, stop_at_node_generation=(2,))
    assert counter.generation == (2,)
    assert counter.get_data() == ("abc",)


def test_streamed_data_generation_with_stopping_partial():
    with FlowHDL() as hdl:
        hdl.counter = StreamCounter()
        hdl.forever = TakeForeverDefault(hdl.counter, hdl.forever)

    counter = cast(StreamCounter, hdl.counter)

    with pytest.raises(TerminateLimitReached):
        hdl.run_until_complete(terminate_on_node_error=True, stop_at_node_generation=(3, 1))
    assert counter.generation == (3, 1)
    assert counter._data[(2,)] == ("abc",)
    assert counter._data[(3, 1)] == ("b",)


@pytest.mark.parametrize("stop_at_generation", [(0, 0), (0, 1), (0, 2)])
def test_streamed_data_generation_with_stopping_partial_before_ever_finishing(
    stop_at_generation,
):
    with FlowHDL() as hdl:
        hdl.counter = StreamCounter()
        hdl.forever = TakeForeverDefault(hdl.counter, hdl.forever)

    counter = cast(StreamCounter, hdl.counter)

    with pytest.raises(TerminateLimitReached):
        hdl.run_until_complete(terminate_on_node_error=True, stop_at_node_generation=stop_at_generation)

    assert counter.generation == stop_at_generation
    assert counter.get_data(0) is None
    assert counter.get_data(1) == ("abc"[stop_at_generation[1]],)


@pytest.mark.parametrize(
    "stop_at_generation, actual_generation, last_data",
    [
        ((0, 0), (0, 0), (None, ("a",))),
        ((0, 1), (0, 1), (None, ("b",))),
        ((0, 2), (0, 2), (None, ("c",))),
        ((0, 3), (0,), (("abc",), None)),
        ((0,), (0,), (("abc",), None)),
        ((0, 1), (0, 1), (None, ("b",))),
        ((0, 2), (0, 2), (None, ("c",))),
        ((0, 3), (0,), (("abc",), None)),
        ((1,), (1,), (("abc",), None)),
        ((1, 0), (1, 0), (("abc",), ("a",))),
        ((1, 1), (1, 1), (("abc",), ("b",))),
        ((1, 2), (1, 2), (("abc",), ("c",))),
        ((1, 3), (1,), (("abc",), None)),
        ((2,), (2,), (("abc",), None)),
        ((2, 0), (2, 0), (("abc",), ("a",))),
        ((2, 1), (2, 1), (("abc",), ("b",))),
        ((2, 2), (2, 2), (("abc",), ("c",))),
        ((2, 3), (2,), (("abc",), None)),
        ((3,), (3,), (("abc",), None)),
    ],
)
def test_streamed_data_generation_all(stop_at_generation, actual_generation, last_data):
    with FlowHDL() as hdl:
        hdl.counter = StreamCounter()
        hdl.forever = TakeForeverDefault(hdl.counter, hdl.forever)

    counter = cast(StreamCounter, hdl.counter)

    with pytest.raises(TerminateLimitReached):
        hdl.run_until_complete(terminate_on_node_error=True, stop_at_node_generation=stop_at_generation)
    assert counter.generation == actual_generation
    assert counter.get_data(0) == last_data[0]
    assert counter.get_data(1) == last_data[1]
