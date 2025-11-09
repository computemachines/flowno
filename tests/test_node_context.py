from flowno import FlowHDL, node, current_node, current_context
import flowno
import pytest


def test_node_context_factory():
    @node
    async def DummyNode():
        context = current_context()
        assert context is not None
        assert context.func_name == "DummyNode"
        return 42

    with FlowHDL() as f:
        f.dummy = DummyNode()
    
    def context_factory(node):
        return node._original_call

    f.run_until_complete(context_factory=context_factory)


def test_current_node():
    @node
    async def DummyNode():
        current = current_node()
        assert current is not None
        assert current._original_call.func_name == "DummyNode"
        return 42

    with FlowHDL() as f:
        f.dummy = DummyNode()
    
    f.run_until_complete()
    assert f.dummy.get_data() == (42,)