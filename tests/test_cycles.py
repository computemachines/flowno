"""
Tests for cycle handling in the Flowno dataflow programming library.

This module tests various cyclic dataflow configurations to ensure proper execution
and termination behavior within the FlowHDL context.
"""

import logging

from flowno import FlowHDL, node, TerminateLimitReached
from flowno.core.flow.instrumentation import LogInstrument as FlowLogInstrument
from flowno.core.event_loop.instrumentation import LogInstrument as EventLoopLogInstrument
from flowno.core.node_base import NodePlaceholder
from flowno.core.types import OutputPortIndex
from pytest import raises

logger = logging.getLogger(__name__)

@node
async def Identity(x: int) -> int:
    return x

@node
async def Increment(x: int = 42) -> int:
    return x + 1


def test_simple_cycle_1():
    with FlowHDL() as f:
        f.increment = Increment(f.increment)
    assert not isinstance(f.increment, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.increment: (0,)})

    assert f.increment.get_data() == (43,)


def test_simple_cycle_2():
    with FlowHDL() as f:
        f.increment = Increment(f.increment)
    assert not isinstance(f.increment, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.increment: (1,)})

    assert f.increment.get_data() == (44,)


def test_simple_cycle_3():
    with FlowHDL() as f:
        f.increment = Increment(f.increment)
    assert not isinstance(f.increment, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.increment: (2,)})

    assert f.increment.get_data() == (45,)


@node
async def ToggleInitTrue(x: bool = True) -> bool:
    return not x


def test_simple_toggle_cycle_1():
    with FlowHDL() as f:
        f.toggle = ToggleInitTrue(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (0,)})

    assert f.toggle.get_data() == (False,)


def test_simple_toggle_cycle_2():
    with FlowHDL() as f:
        f.toggle = ToggleInitTrue(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (1,)})

    assert f.toggle.get_data() == (True,)


def test_simple_toggle_cycle_3():
    with FlowHDL() as f:
        f.toggle = ToggleInitTrue(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (2,)})

    assert f.toggle.get_data() == (False,)


@node
async def ToggleInitFalse(x: bool = False) -> bool:
    return not x


def test_simple_toggle_false_cycle_1():
    with FlowHDL() as f:
        f.toggle = ToggleInitFalse(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (0,)})

    assert f.toggle.get_data() == (True,)


def test_simple_toggle_false_cycle_2():
    with FlowHDL() as f:
        f.toggle = ToggleInitFalse(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (1,)})

    assert f.toggle.get_data() == (False,)


def test_simple_toggle_false_cycle_3():
    with FlowHDL() as f:
        f.toggle = ToggleInitFalse(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (2,)})

    assert f.toggle.get_data() == (True,)


@node(multiple_outputs=True)
async def Swap(x: int = -10, y: int = 13) -> tuple[int, int]:
    return y, x

@node
async def Add(x: int, y: int) -> int:
    return x + y


def test_multi_input_1():
    with FlowHDL() as f:
        f.add = Add(5, 17)
    assert not isinstance(f.add, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.add: (0,)})

    assert f.add.get_data() == (22,)


def test_multi_input_2():
    with FlowHDL() as f:
        f.increment1 = Increment(f.add)
        f.add = Add(f.increment1, 17)
    assert not isinstance(f.add, NodePlaceholder)
    assert not isinstance(f.increment1, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.add: (0,)})

    assert f.add.get_data() == (43 + 17,)


def test_multi_input_3():
    with FlowHDL() as f:
        f.increment1 = Increment(f.add)
        f.add = Add(f.increment1, f.increment1)
    assert not isinstance(f.add, NodePlaceholder)
    assert not isinstance(f.increment1, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.add: (0,)})

    assert f.add.get_data() == (43 + 43,)


def test_simple_swapper_cycle_with_ident():
    with FlowHDL() as f:
        f.swap = Swap(f.ident0, f.ident1)
        f.ident0 = Identity(f.swap.output(0))
        f.ident1 = Identity(f.swap.output(1))
    assert not isinstance(f.swap, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.swap: (0,)})

    assert f.swap.get_data() == (13, -10)



def test_reused_classvars1():
    @node(multiple_outputs=True)
    async def Snap(x: int = -10, y: int = 13) -> tuple[int, int]:
        return y, x

    with FlowHDL() as f1:
        f1.swap = Swap(f1.swap.output(0), f1.swap.output(1))
    assert not isinstance(f1.swap, NodePlaceholder)
    with raises(TerminateLimitReached):
        f1.run_until_complete(stop_at_node_generation={f1.swap: (0,)})

    with FlowHDL() as f2:
        f2.swap = Swap(f2.swap.output(0), f2.swap.output(1))
    assert not isinstance(f2.swap, NodePlaceholder)
    with raises(TerminateLimitReached):
        f2.run_until_complete(stop_at_node_generation={f2.swap: (0,)})

    assert f2.swap.get_data() == (13, -10)


def test_simple_swapper_cycle_1():
    with FlowHDL() as f:
        f.swap = Swap(f.swap.output(0), f.swap.output(1))
    assert not isinstance(f.swap, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.swap: (0,)})

    assert f.swap.get_data() == (13, -10)


def test_simple_swapper_cycle_2():
    with FlowHDL() as f:
        f.swap = Swap(f.swap.output(0), f.swap.output(1))
    assert not isinstance(f.swap, NodePlaceholder)

    with FlowLogInstrument():
        with EventLoopLogInstrument():
            with raises(TerminateLimitReached):
                f.run_until_complete(stop_at_node_generation={f.swap: (1,)})

    assert f.swap.get_data() == (-10, 13)


def test_simple_swapper_cycle_3():
    with FlowHDL() as f:
        f.swap = Swap(f.swap.output(0), f.swap.output(1))
    assert not isinstance(f.swap, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.swap: (2,)})

    assert f.swap.get_data() == (13, -10)


@node
class ToggleCounter:
    count: int = 0

    async def call(self, x: bool = True) -> bool:
        self.count += 1
        return not x


def test_stateful_cycle0():
    with FlowHDL() as f:
        f.toggle = ToggleCounter(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (0,)})

    assert f.toggle.get_data() == (False,)
    assert f.toggle.count == 1


def test_stateful_cycle1():
    with FlowHDL() as f:
        f.toggle = ToggleCounter(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (1,)})

    assert f.toggle.get_data() == (True,)
    assert f.toggle.count == 2


def test_stateful_cycle2():
    with FlowHDL() as f:
        f.toggle = ToggleCounter(f.toggle)
    assert not isinstance(f.toggle, NodePlaceholder)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.toggle: (2,)})

    assert f.toggle.get_data() == (False,)
    assert f.toggle.count == 3
