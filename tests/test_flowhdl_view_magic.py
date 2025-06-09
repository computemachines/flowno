import pytest
import inspect
from flowno import node
from flowno.core.flow_hdl import FlowHDL
from flowno.core.flow_hdl_view import FlowHDLView
from flowno.core.node_base import DraftNode, OutputPortRefPlaceholder, DraftInputPortRef
from typing import Any


@node
async def Add(x: int, y: int) -> int:
    return x + y

@node
async def Source(value: Any) -> Any:
    return value


#––– TESTS –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

def test_set_and_get_simple_attribute():
    """
    Assign a “private” (_something) vs. a public attribute name and ensure __setattr__/__getattribute__
    behave as expected. Anything starting with '_' should be stored on the instance, not in _nodes.
    """
    hdl = FlowHDLView(lambda _: None)  # Dummy callback for on_register_finalized_node
    # Setting a private attribute: goes to object __dict__, not _nodes
    hdl._foo = 123
    assert hdl._foo == 123
    # Setting a public name should populate _nodes
    hdl.bar = 456
    # Accessing hdl.bar should return whatever was in _nodes
    assert hdl.bar == 456


def test_getattr_returns_placeholder_before_finalize():
    """
    If we reference an attribute in a FlowHDLView before it’s ever been set,
    __getattr__ should return a NodePlaceholder (not raise immediately).
    """
    hdl = FlowHDLView(lambda _: None)  # Dummy callback for on_register_finalized_node
    placeholder = hdl.some_node  # not defined yet
    from flowno.core.node_base import NodePlaceholder
    assert isinstance(placeholder, NodePlaceholder)
    assert placeholder.name == "some_node"


def test_connect_two_nodes_out_of_order_and_finalize():
    """
    Build a tiny subgraph in FlowHDL: f.out = Add(f.a, f.b), then define f.a := Source(1), f.b := Source(2).
    After exiting the with-block or calling _finalize() explicitly, the graph should have
    two Source nodes feeding an Add node. We can then inspect the finalized connections.
    """
    with FlowHDL() as f:
        # f.a and f.b do not exist yet, so f.a and f.b are placeholders
        f.result = Add(f.a, f.b)
        # now define f.a and f.b
        f.a = Source(1)
        f.b = Source(2)
    # at this point, __exit__ has run _finalize(), so f.result is a FinalizedNode
    from flowno.core.node_base import FinalizedNode
    assert isinstance(f.result, FinalizedNode)
    # Check that the Add node’s two inputs are connected to the two Source nodes
    input_ports = f.result._input_ports
    # There should be exactly two input ports
    assert set(input_ports.keys()) == {0, 1}
    # upstream of input 0 is f.a, upstream of input 1 is f.b
    upstreams = [p.connected_output.node for p in input_ports.values()]
    # Each upstream should be the finalized Source node we defined
    assert upstreams[0] is f.a
    assert upstreams[1] is f.b


def test_missing_definition_raises_on_finalize():
    """
    If we reference a placeholder inside FlowHDL but never define it, finalize should fail.
    """
    with pytest.raises(AttributeError) as excinfo:
        with FlowHDL() as f:
            f.foo = Add(f.bar, Source(3))  # f.bar never defined
    # The message should mention that 'bar' is not defined
    assert "bar" in str(excinfo.value)


def test_connect_to_non_draftnode_raises():
    """
    Assign a non‐DraftNode to a name, then try to wire to it; finalize should complain.
    """
    # Reference f.baz before it is defined so a placeholder is captured

    # Now assign a non-DraftNode value to f.baz
    with pytest.raises(AttributeError) as excinfo:
        with FlowHDL() as f:
            f.foo = Add(f.baz, Source(3))
            f.baz = 999

    assert "baz" in str(excinfo.value)


def test_unconnected_input_without_default_value_raises():
    """
    If a DraftNode has an input port with no default value, and nobody connects it,
    finalize() should raise. We simulate this by making a node with required args
    and never wiring it.
    """
    @node
    async def NeedsTwo(x, y):
        return x + y

    f = FlowHDL()
    with pytest.raises(AttributeError) as excinfo:
        with f:
            # f.one = NeedsTwo()  # never supplying both inputs
            f.one = NeedsTwo(1)  # missing second argument y and no default
    assert "is not connected and has no default value" in str(excinfo.value)

def test_accessing_nonexistent_node_after_finalize_raises():
    """
    After finalizing, trying to access a node that was never defined should raise.
    """

    with FlowHDL() as f:
        pass

    with pytest.raises(AttributeError) as excinfo:
        _ = f.non_existent_node
