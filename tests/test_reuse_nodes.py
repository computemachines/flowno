from flowno import FlowHDL, node
from pytest import raises

from flowno.core.flow.flow import TerminateLimitReached

@node
async def Identity(x: int) -> int:
    return x

def test_simple_swapper_cycle_with_ident():
    @node(multiple_outputs=True)
    async def Swap(x: int = -10, y: int = 13) -> tuple[int, int]:
        return y, x
    
    with FlowHDL() as f1:
        f1.swap = Swap(f1.ident0, f1.ident1)
        f1.ident0 = Identity(f1.swap.output(0))
        f1.ident1 = Identity(f1.swap.output(1))


    with FlowHDL() as f2:
        f2.swap = Swap(f2.swap.output(0), f2.swap.output(1))
    with raises(TerminateLimitReached):
        f2.run_until_complete(stop_at_node_generation={f2.swap: (0,)})

    assert f2.swap.get_data() == (13, -10)
