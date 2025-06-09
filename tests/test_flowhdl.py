import timeit
from typing import TypeVar, Union, cast

from flowno import FlowHDL, node, sleep, TerminateLimitReached
from flowno.core.node_base import (
    DraftNode,
    DraftOutputPortRef,
    FinalizedNode,
    NodePlaceholder,
    OutputPortRefPlaceholder,
)
from flowno.core.types import InputPortIndex, OutputPortIndex
from pytest import raises


T = TypeVar('T')
T_NUM = TypeVar("T_NUM", int, float)
T2 = TypeVar('T2')

@node
async def ident(x: Union[T, None] = None, /) -> Union[T, None]:
    return x




@node
async def double(x: T_NUM) -> T_NUM:
    return x * 2


def test_hdl_context_placeholders_outside_context():
    f = FlowHDL().__enter__()

    placeholder_node = f.dummy_node
    assert isinstance(placeholder_node, NodePlaceholder)
    assert placeholder_node.name == "dummy_node"

    f.__exit__(None, None, None)

    with raises(AttributeError):
        f.other_dummy_node


def test_hdl_finalize_trivial():

    @node
    async def dummy_constant() -> int:
        return 42

    with FlowHDL() as flow:
        flow.dummy_node = dummy_constant()
        assert isinstance(flow.dummy_node, DraftNode)
    assert isinstance(flow.dummy_node, FinalizedNode)

    flow.run_until_complete()
    assert flow.dummy_node.get_data() == (42,)


@node(multiple_outputs=True)
async def dummy_constant_multi() -> tuple[int, int]:
    return 42, -101


def test_hdl_finalize_multiple_outputs():
    with FlowHDL() as flow:
        flow.dummy_node = dummy_constant_multi()
        assert isinstance(flow.dummy_node, DraftNode)
    assert not isinstance(flow.dummy_node, NodePlaceholder)

    flow.run_until_complete()
    assert flow.dummy_node.get_data() == (42, -101)


def test_hdl_finalize_using_multiple_outputs():
    with FlowHDL() as flow:
        flow.dummy_node = dummy_constant_multi()
        flow.output1 = ident(flow.dummy_node.output(0))
        flow.output2 = ident(flow.dummy_node.output(1))

    assert not isinstance(flow.dummy_node, NodePlaceholder)
    assert not isinstance(flow.output1, NodePlaceholder)
    assert not isinstance(flow.output2, NodePlaceholder)

    flow.run_until_complete()
    assert flow.dummy_node.get_data(0) == (42, -101)
    assert flow.output1.get_data(0) == (42,)
    assert flow.output2.get_data(0) == (-101,)


def test_simple_cycle():
    with FlowHDL() as f:
        f.dummy_node = ident(f.dummy_node)

    with raises(TerminateLimitReached):
        f.run_until_complete((10,))


def test_simple_connection():

    @node
    async def dummy_constant() -> int:
        return 10

    with FlowHDL() as f:
        f.node1 = dummy_constant()
        f.node2 = ident(f.node1)

    constant = cast(dummy_constant, f.node1)
    identity = cast(ident, f.node2)

    assert dict(constant._input_ports) == {}
    assert constant.get_output_nodes() == [identity]

    assert identity._input_ports[0].connected_output.node is constant
    assert identity._input_ports[0].connected_output.port_index == InputPortIndex(0)


def test_out_of_order_definition():

    @node
    async def dummy_constant() -> int:
        return 42

    with FlowHDL() as f:
        f.output = ident(f.input)
        f.input = dummy_constant()

    f.run_until_complete()

    assert isinstance(f.output, FinalizedNode)
    input_node = cast(dummy_constant, f.input)
    output_node = cast(ident, f.output)

    assert input_node.get_data(0) == (42,)
    assert output_node.get_data(0) == (42,)


def test_criss_cross_cycle():
    with FlowHDL() as f:
        f.even = ident(f.odd)
        f.odd = ident(f.even)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(10,))


def test_anonymous_node():
    with FlowHDL() as f:
        f.final = ident(ident(42))

    f.run_until_complete()

    final = cast(ident, f.final)
    assert final.get_data(0) == (42,)


def test_nested_anonymous_node():
    with FlowHDL() as f:
        f.final = ident(ident(ident(42)))

    f.run_until_complete()

    final = cast(ident, f.final)
    assert final.get_data(0) == (42,)


@node
async def delayed_dummy_constant() -> int:
    _ = await sleep(0.1)
    return 10


def test_node_delay():
    with FlowHDL() as f:
        f.delayed = ident(delayed_dummy_constant())

    duration = timeit.timeit(lambda: f.run_until_complete(), number=1)
    assert 0.1 <= duration <= 0.16

    delayed = cast(ident, f.delayed)

    assert delayed.get_data(0) == (10,)


@node(multiple_outputs=True)
async def IdentTuple(x: T2) -> tuple[T2]:
    return (x,)


def test_placeholders():
    with FlowHDL() as f:
        f.node1 = ident(f.node1)
        f.node2 = IdentTuple(f.node2)
        f.node3 = ident(f.node3.output(0))
        f.node4 = IdentTuple(f.node4.output(0))
        assert isinstance(f.node1, DraftNode)
        assert isinstance(f.node99, NodePlaceholder)
        assert f.node99.name == "node99"
        assert isinstance(f.node1.output(0), DraftOutputPortRef)
        assert isinstance(f.node2.output(0), DraftOutputPortRef)


@node(multiple_outputs=True)
async def DummyTuple():
    return 42, 10


@node
async def AddTwo(a: int, b: int) -> int:
    return a + b


def test_flow_with_tuple():
    with FlowHDL() as f:
        f.tuple = DummyTuple()
        f.add = AddTwo(f.tuple.output(0), f.tuple.output(1))

    f.run_until_complete(terminate_on_node_error=True)

    add = cast(AddTwo, f.add)
    assert add.get_data() == (52,)


# @node
# def identity_single_output[T](x: T) -> T:
#     return x

# @node
# def ten() -> str:
#     return "ten"

# @node
# def to_upper(x: str) -> str:
#     return x.upper()

# def test_linear_flow():
#     with FlowHDL() as f:
#         f.constant = ten()
#         f.passthrough1 = identity_single_output(f.constant)
#         f.passthrough2 = identity_single_output(f.passthrough1)

#     f.run_until_complete()
#     assert f.passthrough2.last_data == "ten"

# def test_conditional():
#     with FlowHDL() as f:
#         f.constant = ten()
#         with Match(f.constant, yes="ten", maybe=lambda x: x.upper() == "TEN", no=default) as f.switch:
#             f.switch.yes = identity_single_output(f.constant)
#             f.switch.maybe = Constant("You said Ten or TeN or tEN or ...")
#             f.switch.no = Constant("bummer")
#         f.passthrough = identity_single_output(f.switch)

#     f.run_until_complete()

#     assert f.passthrough.last_data == "ten"
