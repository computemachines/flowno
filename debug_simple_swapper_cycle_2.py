#!/usr/bin/env python3
"""
Debug file for test_simple_swapper_cycle_2 extracted from tests/test_cycles.py

This debug script isolates the specific test case for easier debugging and analysis.
"""

import logging
from flowno import FlowHDL, node, TerminateLimitReached
from flowno.core.flow.instrumentation import LogInstrument as FlowLogInstrument
from flowno.core.event_loop.instrumentation import LogInstrument as EventLoopLogInstrument
from flowno.core.node_base import NodePlaceholder
from pytest import raises

logger = logging.getLogger(__name__)

@node(multiple_outputs=True)
async def Swap(x: int = -10, y: int = 13) -> tuple[int, int]:
    return y, x


def test_simple_swapper_cycle_2():
    """
    Extracted test case: test_simple_swapper_cycle_2
    
    This test creates a cycle where a Swap node's outputs are fed back as its inputs,
    and runs until generation 1, expecting the swapped values.
    """
    with FlowHDL() as f:
        f.swap = Swap(f.swap.output(0), f.swap.output(1))
    assert not isinstance(f.swap, NodePlaceholder)

    with FlowLogInstrument():
        with EventLoopLogInstrument():
            with raises(TerminateLimitReached):
                f.run_until_complete(stop_at_node_generation={f.swap: (1,)})

    assert f.swap.get_data() == (-10, 13)


if __name__ == "__main__":
    # Run the test directly when executed as a script
    print("Running test_simple_swapper_cycle_2...")
    try:
        test_simple_swapper_cycle_2()
        print("✓ Test completed successfully!")
    except Exception as e:
        print(f"✗ Test failed with error: {e}")
        raise
