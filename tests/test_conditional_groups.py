from flowno import FlowHDL, node
from flowno.core.node_base import Constant


@node
async def Inc(x: int) -> int:
    return x + 1


@node
async def Identity(x: int) -> int:
    return x


@node.template
def MyGroup(f, x: int):
    f.inc = Inc(x)
    f.inc_2 = Inc(f.inc)
    return f.inc_2


@node.template
def OuterGroup(f, x: int):
    f.inner = MyGroup(x)
    f.out = MyGroup(f.inner)
    return f.out


def test_group_if_true():
    with FlowHDL() as f:
        f.b = MyGroup(1).if_(True)
    f.run_until_complete()
    assert f.b.get_data() == (3,)


def test_group_if_false():
    with FlowHDL() as f:
        f.b = MyGroup(1).if_(False)
    f.run_until_complete()
    assert f.b.get_data() is None


def test_group_named_constant():
    with FlowHDL() as f:
        f.c = Constant(1)
        f.b = MyGroup(f.c).if_(True)
    f.run_until_complete()
    assert f.b.get_data() == (3,)


def test_group_forward_reference_input():
    with FlowHDL() as f:
        f.b = MyGroup(f.c).if_(True)
        f.c = Constant(1)
    f.run_until_complete()
    assert f.b.get_data() == (3,)


def test_group_forward_reference_predicate():
    with FlowHDL() as f:
        f.b = MyGroup(1).if_(f.cond)
        f.cond = Constant(True)
    f.run_until_complete()
    assert f.b.get_data() == (3,)


def test_group_chained_conditions_true_false():
    with FlowHDL() as f:
        first = MyGroup(1).if_(True)
        f.b = first.if_(False)
    f.run_until_complete()
    assert f.b.get_data() is None


def test_group_chained_conditions_true_true():
    with FlowHDL() as f:
        first = MyGroup(1).if_(True)
        f.b = first.if_(True)
    f.run_until_complete()
    assert f.b.get_data() == (3,)


def test_nested_group_if_true():
    with FlowHDL() as f:
        f.b = OuterGroup(1).if_(True)
    f.run_until_complete()
    assert f.b.get_data() == (5,)


def test_nested_group_if_false():
    with FlowHDL() as f:
        f.b = OuterGroup(1).if_(False)
    f.run_until_complete()
    assert f.b.get_data() is None


def test_group_if_rewires_consumers():
    with FlowHDL() as f:
        g = MyGroup(1)
        f.c = Inc(g)
        f.result = g.if_(True)
    f.run_until_complete()
    assert f.c._input_ports[0].connected_output.node is f.result
