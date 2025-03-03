from flowno import FlowHDL, node
from flowno.core.flow.flow import TerminateLimitReached
from pytest import raises


@node
class Counter:
    count: int = 0

    async def call(self) -> int:
        self.count += 1
        return self.count


@node
class Accumulator:
    total: float = 0.0

    async def call(self, x: float = 1) -> float:
        self.total += x
        return self.total


def test_basic_stateful():
    with FlowHDL() as f:
        f.counter = Counter()

    f.run_until_complete()
    assert f.counter.get_data() == (1,)


def test_stateful_with_input():
    with FlowHDL() as f:
        f.acc = Accumulator(2.5)

    f.run_until_complete()
    assert f.acc.get_data() == (2.5,)


def test_stateful_cycle0():
    with FlowHDL() as f:
        f.acc = Accumulator(f.acc)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(0,))

    assert f.acc.get_data() == (1.0,)


def test_stateful_cycle1():
    with FlowHDL() as f:
        f.acc = Accumulator(f.acc)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(1,))

    assert f.acc.get_data() == (2.0,)


def test_stateful_cycle2():
    with FlowHDL() as f:
        f.acc = Accumulator(f.acc)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(2,))

    assert f.acc.get_data() == (4.0,)


def test_stateful_cycle3():
    with FlowHDL() as f:
        f.acc = Accumulator(f.acc)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation=(3,))

    assert f.acc.get_data() == (8.0,)
