from flowno import FlowHDL, node, current_node, current_context, sleep
from flowno.core.flow_hdl_view import FlowHDLView
import flowno
import pytest


@node
async def MyConstant() -> int:
    return 42


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


def test_current_context_outside_flow():
    with pytest.raises(RuntimeError, match="current_context\\(\\) called outside of a flow"):
        current_context()


def test_current_context_without_factory():
    @node
    async def DummyNode():
        context = current_context()  # This will raise
        return 42

    with FlowHDL() as f:
        f.dummy = DummyNode()
    
    # No context_factory provided, so current_context should raise
    with pytest.raises(RuntimeError, match="No context factory provided"):
        f.run_until_complete()


def test_current_context_different_factories():
    @node
    async def NodeA():
        context = current_context()
        assert context == "NodeA"
        return 42

    @node
    async def NodeB():
        context = current_context()
        assert context == "NodeB"
        return 84

    with FlowHDL() as f:
        f.a = NodeA()
        f.b = NodeB()
    
    def context_factory(node):
        return node._original_call.func_name

    f.run_until_complete(context_factory=context_factory)
    assert f.a.get_data() == (42,)
    assert f.b.get_data() == (84,)


def test_current_context_factory_returns_node():
    @node
    async def DummyNode():
        context = current_context()
        assert context is not None
        assert hasattr(context, '_original_call')
        return 42

    with FlowHDL() as f:
        f.dummy = DummyNode()
    
    def context_factory(node):
        return node

    f.run_until_complete(context_factory=context_factory)


def test_current_context_in_group():
    @node
    async def InnerNode(x: int):
        context = current_context()
        assert context is not None
        assert context.func_name == "InnerNode"
        return x + 1

    @node.template
    def MyGroup(f: FlowHDLView, g_input: int):
        f.inner = InnerNode(g_input)
        return f.inner

    with FlowHDL() as f:
        f.constant = MyConstant()
        f.result = MyGroup(f.constant)
    
    def context_factory(node):
        return node._original_call

    f.run_until_complete(context_factory=context_factory)
    assert f.result.get_data() == (43,)  # 42 + 1


def test_current_node_in_group():
    @node
    async def InnerNode(x: int):
        current = current_node()
        assert current is not None
        assert current._original_call.func_name == "InnerNode"
        return x + 1

    @node.template
    def MyGroup(f: FlowHDLView, g_input: int):
        f.inner = InnerNode(g_input)
        return f.inner

    with FlowHDL() as f:
        f.constant = MyConstant()
        f.result = MyGroup(f.constant)
    
    f.run_until_complete()
    assert f.result.get_data() == (43,)


def test_current_node_outside():
    # Outside any flow or node, current_node should return None
    assert current_node() is None


def test_concurrent_nodes_with_sleep():
    import time
    
    @node
    async def NodeA() -> int:
        return 42

    @node
    async def NodeB(a: int) -> int:
        # Check current_node before sleep
        current_before = current_node()
        assert current_before is not None
        assert current_before._original_call.func_name == "NodeB"
        await sleep(1.0)  # Sleep for 1 second
        # After reentry, current_node should still be NodeB
        current_after = current_node()
        assert current_after is not None
        assert current_after._original_call.func_name == "NodeB"
        assert current_before is current_after  # Should be the same node instance
        return a + 1

    @node
    async def NodeC(a: int) -> int:
        # Check current_node before sleep
        current_before = current_node()
        assert current_before is not None
        assert current_before._original_call.func_name == "NodeC"
        await sleep(1.0)  # Sleep for 1 second
        # After reentry, current_node should still be NodeC
        current_after = current_node()
        assert current_after is not None
        assert current_after._original_call.func_name == "NodeC"
        assert current_before is current_after  # Should be the same node instance
        return a + 2

    start_time = time.time()
    with FlowHDL() as f:
        f.a = NodeA()
        f.b = NodeB(f.a)
        f.c = NodeC(f.a)
    
    f.run_until_complete()
    end_time = time.time()
    
    # Both B and C should complete, and since they run concurrently,
    # total time should be around 1 second + overhead, not 2 seconds
    total_time = end_time - start_time
    assert 1.0 <= total_time < 2.0  # Should be less than 2 seconds if concurrent
    
    assert f.b.get_data() == (43,)  # 42 + 1
    assert f.c.get_data() == (44,)  # 42 + 2


def test_concurrent_nodes_different_sleep_times():
    import time
    
    @node
    async def NodeA() -> int:
        return 100

    @node
    async def NodeB(a: int) -> int:
        # Check current_node before sleep
        current_before = current_node()
        assert current_before is not None
        assert current_before._original_call.func_name == "NodeB"
        await sleep(0.5)  # Shorter sleep
        # After reentry, current_node should still be NodeB
        current_after = current_node()
        assert current_after is not None
        assert current_after._original_call.func_name == "NodeB"
        assert current_before is current_after  # Should be the same node instance
        return a * 2

    @node
    async def NodeC(a: int) -> int:
        # Check current_node before sleep
        current_before = current_node()
        assert current_before is not None
        assert current_before._original_call.func_name == "NodeC"
        await sleep(1.0)  # Longer sleep
        # After reentry, current_node should still be NodeC
        current_after = current_node()
        assert current_after is not None
        assert current_after._original_call.func_name == "NodeC"
        assert current_before is current_after  # Should be the same node instance
        return a * 3

    start_time = time.time()
    with FlowHDL() as f:
        f.a = NodeA()
        f.c = NodeC(f.a)
        f.b = NodeB(f.a)
    
    f.run_until_complete()
    end_time = time.time()
    
    # Both B and C should run concurrently, so total time should be around the max sleep time
    total_time = end_time - start_time
    assert 0.9 <= total_time < 1.5  # Should be close to 1.0 seconds
    
    assert f.b.get_data() == (200,)  # 100 * 2
    assert f.c.get_data() == (300,)  # 100 * 3


def test_concurrent_nodes_no_sleep():
    import time
    
    @node
    async def NodeA() -> int:
        return 10

    @node
    async def NodeB(a: int) -> int:
        return a + 5

    @node
    async def NodeC(a: int) -> int:
        return a + 10

    start_time = time.time()
    with FlowHDL() as f:
        f.a = NodeA()
        f.b = NodeB(f.a)
        f.c = NodeC(f.a)
    
    f.run_until_complete()
    end_time = time.time()
    
    # Should be very fast since no sleeps
    total_time = end_time - start_time
    assert total_time < 0.1
    
    assert f.b.get_data() == (15,)  # 10 + 5
    assert f.c.get_data() == (20,)  # 10 + 10