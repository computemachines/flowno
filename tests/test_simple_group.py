from flowno import FlowHDL, node
from flowno.core.flow_hdl_view import FlowHDLView
from flowno.core.group_node import DraftGroupNode
from flowno.core.node_base import FinalizedNode

@node
async def MyConstant() -> int:
    return 42

@node
async def Increment(a: int) -> int:
    return a + 1

@node.template
def MyGroup(f: FlowHDLView, g_input: int):
    f.incremented_twice = Increment(Increment(g_input))
    return f.incremented_twice

@node
async def Sink(x: int) -> None:
    pass

def test_group_expansion():
    with FlowHDL() as f:
        f.constant = MyConstant()
        f.result = MyGroup(f.constant)
        f.sink = Sink(f.result)
    f.run_until_complete()

    # result should be a finalized node that is not a DraftGroupNode
    assert isinstance(f.result, FinalizedNode)
    assert not isinstance(f.result._draft_node, DraftGroupNode)

    # sink's input should connect directly to result
    assert f.sink._input_ports[0].connected_output.node is f.result

    # ensure no finalized nodes in the flow originate from a DraftGroupNode
    for node in f._flow.node_tasks:
        assert not isinstance(node._draft_node, DraftGroupNode)
