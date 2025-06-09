import pytest
from flowno import FlowHDL, node

@node
async def NodeA(x: int) -> int:
    return x + 1

@node
async def IsUltimateAnswer(x: int) -> bool:
    return x == 42


def test_propagate_if_runs_when_true():
    with FlowHDL() as f:
        f.node = NodeA(41)
        f.out = NodeA(10).if_(IsUltimateAnswer(f.node))

    f.run_until_complete()
    assert f.out.get_data() == (11,)


def test_propagate_if_skips_when_false():
    with FlowHDL() as f:
        f.node = NodeA(40)
        f.out = NodeA(10).if_(IsUltimateAnswer(f.node))

    f.run_until_complete()
    assert f.out.get_data() is None
