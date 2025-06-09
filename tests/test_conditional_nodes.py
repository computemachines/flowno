from flowno import FlowHDL, node
from flowno.core.node_base import PropagateIf

@node
async def NodeA(x: int) -> int:
    return x + 1

@node
async def IsUltimateAnswer(x: int) -> bool:
    return x == 42


def test_if_helper_runs_when_true():
    with FlowHDL() as f:
        f.first = NodeA(41)
        f.out = NodeA(10).if_(IsUltimateAnswer(f.first))
    f.run_until_complete()
    assert f.out.get_data() == (11,)


def test_if_helper_skips_when_false():
    with FlowHDL() as f:
        f.first = NodeA(1)
        f.out = NodeA(10).if_(IsUltimateAnswer(f.first))
    f.run_until_complete()
    assert f.out.get_data() is None
