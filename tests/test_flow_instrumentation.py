"""Tests for FlowInstrument and related instrumentation functionality."""

from typing import Any
from contextlib import contextmanager
from typing_extensions import override

import pytest
from flowno import node, FlowHDL
from flowno.core.flow.instrumentation import FlowInstrument, get_current_flow_instrument
from flowno.core.flow.flow import Flow
from flowno.core.node_base import FinalizedNode


@node
async def ConstantNode(value: int = 5) -> int:
    """A simple node that returns a constant value."""
    return value


@node
async def DoubleNode(value: int) -> int:
    """A simple node that doubles its input."""
    return value * 2


@node
async def AddNode(x: int, y: int) -> int:
    """A simple node that adds two numbers."""
    return x + y


class CollectingInstrument(FlowInstrument):
    """An instrument that tracks flow execution events."""
    
    def __init__(self):
        super().__init__()
        self.flow_started = False
        self.flow_ended = False
        self.nodes_registered: list[FinalizedNode] = []
        self.nodes_visited: list[FinalizedNode] = []
        self.nodes_emitted: list[tuple[FinalizedNode, Any, int]] = []
        self.node_lifecycle_calls: list[tuple[FinalizedNode, int]] = []
    
    @override
    def on_flow_start(self, flow: Flow) -> None:
        self.flow_started = True
    
    @override
    def on_flow_end(self, flow: Flow) -> None:
        self.flow_ended = True
    
    @override
    def on_node_registered(self, flow: Flow, node: FinalizedNode) -> None:
        self.nodes_registered.append(node)
    
    @override
    def on_node_visited(self, flow: Flow, node: FinalizedNode) -> None:
        self.nodes_visited.append(node)
    
    @override
    def on_node_emitted_data(self, flow: Flow, node: FinalizedNode, data: tuple[Any, ...] | None, run_level: int) -> None:
        self.nodes_emitted.append((node, data, run_level))
    
    @override
    @contextmanager
    def node_lifecycle(self, flow: Flow, node: FinalizedNode, run_level: int):
        self.node_lifecycle_calls.append((node, run_level))
        try:
            yield
        finally:
            pass


def test_flow_start_and_end():
    """Test that flow start and end events are captured."""
    instrument = CollectingInstrument()
    
    with FlowHDL() as f:
        f.constant = ConstantNode(10)
    
    with instrument:
        f.run_until_complete()
    
    assert instrument.flow_started is True
    assert instrument.flow_ended is True


def test_node_registration():
    """Test that node registration events are captured."""
    instrument = CollectingInstrument()
    
    # Use instrument inside FlowHDL context to capture registration
    with instrument:
        with FlowHDL() as f:
            f.constant = ConstantNode(10)
            f.double = DoubleNode(f.constant)
        
        f.run_until_complete()
    
    # Check that nodes were registered (including internal Constant nodes)
    assert len(instrument.nodes_registered) >= 2
    # The nodes should include user-created nodes
    node_reprs = [repr(node) for node in instrument.nodes_registered]
    user_nodes = [r for r in node_reprs if "ConstantNode" in r or "DoubleNode" in r]
    assert len(user_nodes) == 2


def test_node_emitted_data():
    """Test that node data emission events are captured."""
    instrument = CollectingInstrument()
    
    with FlowHDL() as f:
        f.constant = ConstantNode(7)
        f.double = DoubleNode(f.constant)
    
    with instrument:
        f.run_until_complete()
    
    # Check that data emissions were captured (including internal Constant nodes)
    assert len(instrument.nodes_emitted) >= 2
    
    # Find user node emissions
    user_emissions = [(node, data, level) for node, data, level in instrument.nodes_emitted 
                      if "ConstantNode" in repr(node) or "DoubleNode" in repr(node)]
    
    assert len(user_emissions) == 2
    # Should have 7 and 14
    emission_values = [data[0] for node, data, level in user_emissions]
    assert 7 in emission_values
    assert 14 in emission_values


def test_node_lifecycle():
    """Test that node lifecycle context manager is called."""
    instrument = CollectingInstrument()
    
    with FlowHDL() as f:
        f.constant = ConstantNode(3)
        f.double = DoubleNode(f.constant)
    
    with instrument:
        f.run_until_complete()
    
    # Check that node_lifecycle was called for each node (including internal nodes)
    assert len(instrument.node_lifecycle_calls) >= 2
    
    # All should be at run level 0
    for node, run_level in instrument.node_lifecycle_calls:
        assert run_level == 0


def test_multiple_nodes():
    """Test instrumentation with multiple nodes in a flow."""
    instrument = CollectingInstrument()
    
    with FlowHDL() as f:
        f.x = ConstantNode(5)
        f.y = ConstantNode(3)
        f.sum = AddNode(f.x, f.y)
    
    with instrument:
        f.run_until_complete()
    
    # Check that nodes emitted data (including internal Constant nodes)
    assert len(instrument.nodes_emitted) >= 3
    
    # The sum should be 8
    sum_emissions = [data for node, data, level in instrument.nodes_emitted if "AddNode" in repr(node)]
    assert len(sum_emissions) == 1
    assert sum_emissions[0] == (8,)


def test_get_current_flow_instrument():
    """Test that get_current_flow_instrument returns the active instrument."""
    instrument = CollectingInstrument()
    
    # Without context manager, should return NO_OP_INSTRUMENT
    current = get_current_flow_instrument()
    assert not isinstance(current, CollectingInstrument)
    
    # With context manager, should return our instrument
    with instrument:
        current = get_current_flow_instrument()
        assert current is instrument


def test_instrument_context_manager_nesting():
    """Test that instruments can be nested and properly restored."""
    instrument1 = CollectingInstrument()
    instrument2 = CollectingInstrument()
    
    with instrument1:
        assert get_current_flow_instrument() is instrument1
        
        with instrument2:
            assert get_current_flow_instrument() is instrument2
        
        # After exiting instrument2, should be back to instrument1
        assert get_current_flow_instrument() is instrument1


def test_no_instrumentation_doesnt_break_flow():
    """Test that flows work correctly without any instrumentation."""
    with FlowHDL() as f:
        f.constant = ConstantNode(42)
        f.double = DoubleNode(f.constant)
    
    f.run_until_complete()
    
    # Flow should still work correctly
    assert f.double.get_data() == (84,)
