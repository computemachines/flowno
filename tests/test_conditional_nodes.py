from flowno import FlowHDL, node
from flowno.core.node_base import Constant

@node
async def NodeA(x: int) -> int:
    return x + 1

@node
async def IsUltimateAnswer(x: int) -> bool:
    return x == 42


@node
async def IsAllCaps(text: str) -> bool:
    return text.isupper()


def test_if_true():
    with FlowHDL() as f:
        f.node = NodeA(41)
        f.out = NodeA(10).if_(IsUltimateAnswer(f.node))
    f.run_until_complete()
    assert f.out.get_data() == (11,)


def test_if_false():
    with FlowHDL() as f:
        f.node = NodeA(40)
        f.out = NodeA(10).if_(IsUltimateAnswer(f.node))
    f.run_until_complete()
    assert f.out.get_data() is None


def test_basic_constant_input():
    """Node input is a plain constant."""
    with FlowHDL() as f:
        f.node = NodeA(10).if_(IsAllCaps("HELLO"))
    f.run_until_complete()
    assert f.node.get_data() == (11,)


def test_named_constant_node():
    """Node input comes from a named constant node."""
    with FlowHDL() as f:
        f.constant = Constant(10)
        f.node = NodeA(f.constant).if_(IsAllCaps("HELLO"))
    f.run_until_complete()
    assert f.node.get_data() == (11,)


def test_forward_reference_input():
    """Node input is defined after the conditional node."""
    with FlowHDL() as f:
        f.node = NodeA(f.constant).if_(IsAllCaps("HELLO"))
        f.constant = Constant(10)
    f.run_until_complete()
    assert f.node.get_data() == (11,)


def test_forward_reference_predicate():
    """Predicate node defined after the conditional call."""
    with FlowHDL() as f:
        f.node = NodeA(10).if_(f.pred)
        f.pred = IsAllCaps("HELLO")
    f.run_until_complete()
    assert f.node.get_data() == (11,)


def test_predicate_bool_true():
    """Conditional node with bool True should execute."""
    with FlowHDL() as f:
        f.node = NodeA(5).if_(True)
    f.run_until_complete()
    assert f.node.get_data() == (6,)


def test_predicate_bool_false():
    """Conditional node with bool False should skip execution."""
    with FlowHDL() as f:
        f.node = NodeA(5).if_(False)
    f.run_until_complete()
    assert f.node.get_data() is None


def test_named_constant_predicate():
    """Predicate provided by named Constant node."""
    with FlowHDL() as f:
        f.cond = Constant(True)
        f.node = NodeA(5).if_(f.cond)
    f.run_until_complete()
    assert f.node.get_data() == (6,)


def test_forward_reference_predicate_constant():
    """Predicate defined after using it."""
    with FlowHDL() as f:
        f.node = NodeA(5).if_(f.cond)
        f.cond = Constant(True)
    f.run_until_complete()
    assert f.node.get_data() == (6,)


def test_chained_conditions_true_false():
    """Chained .if_ where second condition false should skip."""
    with FlowHDL() as f:
        first = NodeA(5).if_(True)
        f.node = first.if_(False)
    f.run_until_complete()
    assert f.node.get_data() is None


def test_chained_conditions_true_true():
    """Chained .if_ with both predicates true should execute."""
    with FlowHDL() as f:
        first = NodeA(5).if_(True)
        f.node = first.if_(True)
    f.run_until_complete()
    assert f.node.get_data() == (6,)

