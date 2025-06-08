from flowno import FlowHDL, node
from flowno.core.flow_hdl_view import FlowHDLView
from flowno.core.group_node import DraftGroupNode
from flowno.core.node_base import FinalizedNode

@node
async def Const() -> int:
    return 1

@node
async def Add(a: int, b: int) -> int:
    return a + b

@node
async def Inc(x: int) -> int:
    return x + 1

@node
async def Sink(x: int) -> None:
    pass

@node.template
def IncTwice(f: FlowHDLView, x: int):
    f.first = Inc(x)
    f.second = Inc(f.first)
    return f.second

@node.template
def AddGroup(f: FlowHDLView, a: int, b: int = 5):
    f.sum = Add(a, b)
    return f.sum

@node.template
def OuterGroup(f: FlowHDLView, x: int):
    f.inner = IncTwice(x)
    f.out = IncTwice(f.inner)
    return f.out

def _assert_no_groups(flow: FlowHDL) -> None:
    for node in flow._flow.node_tasks:
        assert not isinstance(node._draft_node, DraftGroupNode)


def test_multiple_consumers():
    with FlowHDL() as f:
        f.c = Const()
        f.result = IncTwice(f.c)
        f.s1 = Sink(f.result)
        f.s2 = Sink(Inc(f.result))
    f.run_until_complete()
    assert isinstance(f.result, FinalizedNode)
    assert f.s1._input_ports[0].connected_output.node is f.result
    assert f.s2._input_ports[0].connected_output.node is not f.result
    _assert_no_groups(f)


def test_nested_groups():
    with FlowHDL() as f:
        f.c = Const()
        f.result = OuterGroup(f.c)
        f.s = Sink(f.result)
    f.run_until_complete()
    assert isinstance(f.result, FinalizedNode)
    assert f.s._input_ports[0].connected_output.node is f.result
    _assert_no_groups(f)


def test_group_multiple_inputs():
    with FlowHDL() as f:
        f.a = Const()
        f.b = Inc(f.a)
        f.result = AddGroup(f.a, f.b)
        f.s = Sink(f.result)
    f.run_until_complete()
    assert f.result.get_data() == (3,)
    _assert_no_groups(f)


def test_group_default_parameter():
    with FlowHDL() as f:
        f.c = Const()
        f.result = AddGroup(f.c)
        f.s = Sink(f.result)
    f.run_until_complete()
    assert f.result.get_data() == (6,)
    _assert_no_groups(f)


def test_group_reference_before_definition():
    with FlowHDL() as f:
        f.c = Const()
        f.result = IncTwice(f.c)
        f.s = Sink(f.result)
    f.run_until_complete()
    assert f.result.get_data() == (3,)
    _assert_no_groups(f)


def test_group_used_in_another_group():
    with FlowHDL() as f:
        f.c = Const()
        f.result = OuterGroup(f.c)
        f.extra = Inc(f.result)
    f.run_until_complete()
    assert f.extra.get_data() == (6,)
    _assert_no_groups(f)


def test_group_identity_pass_through():
    @node.template
    def IdentityGroup(flow: FlowHDLView, x: int):
        return x

    with FlowHDL() as f:
        f.c = Const()
        f.result = IdentityGroup(f.c)
        f.s = Sink(f.result)
    f.run_until_complete()
    assert f.result.get_data() == (1,)
    _assert_no_groups(f)


def test_group_fanout():
    with FlowHDL() as f:
        f.c = Const()
        f.result = IncTwice(f.c)
        f.added = Add(f.result, f.result)
    f.run_until_complete()
    assert f.added.get_data() == (6,)
    _assert_no_groups(f)


def test_group_result_reused_multiple_times():
    with FlowHDL() as f:
        f.c = Const()
        f.g = IncTwice(f.c)
        f.s1 = Sink(f.g)
        f.s2 = Sink(f.g)
        f.add = Add(f.g, f.g)
    f.run_until_complete()
    assert f.add.get_data() == (6,)
    _assert_no_groups(f)
