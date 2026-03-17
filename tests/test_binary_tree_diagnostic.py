"""
Diagnostic tests to understand the data flow in nested fork/join patterns.
"""

import pytest
from flowno import node, FlowHDL, Stream


# ============================================================
# Diagnostic nodes that log what they receive
# ============================================================

@node
async def TracingSource(name: str = "source"):
    """Source that logs each yield."""
    for i in range(3):
        print(f"[{name}] yielding {i}")
        yield i
    print(f"[{name}] done")


@node(stream_in=["x"])
async def TracingFork(x: Stream[int], name: str = "fork"):
    """Fork that logs each value."""
    print(f"[{name}] starting")
    async for val in x:
        print(f"[{name}] received {val}, yielding {val}")
        yield val
    print(f"[{name}] done")


@node(stream_in=["a", "b"])
async def TracingJoin2(a: Stream[int], b: Stream[int], name: str = "join"):
    """Join that logs each value from both streams."""
    print(f"[{name}] starting")

    a_values = []
    b_values = []

    print(f"[{name}] reading stream a...")
    async for val in a:
        print(f"[{name}] a received: {val}")
        a_values.append(val)

    print(f"[{name}] reading stream b...")
    async for val in b:
        print(f"[{name}] b received: {val}")
        b_values.append(val)

    total = sum(a_values) + sum(b_values)
    print(f"[{name}] a_values={a_values}, b_values={b_values}, total={total}")
    return total


@node(stream_in=["x"])
async def TracingCollector(x: Stream[int], name: str = "collector"):
    """Collects all values and returns them as a list."""
    values = []
    async for val in x:
        print(f"[{name}] received: {val}")
        values.append(val)
    print(f"[{name}] collected: {values}")
    return values


# ============================================================
# Test 1: Single fork, single consumer
# ============================================================

def test_single_fork_single_consumer():
    """
    Source -> Fork -> Collector

    Expected: [0, 1, 2]
    """
    print("\n=== test_single_fork_single_consumer ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork = TracingFork(f.source, "fork")
        f.collector = TracingCollector(f.fork, "coll")

    f.run_until_complete()

    result = f.collector.get_data()[0]
    print(f"Result: {result}")
    assert result == [0, 1, 2]


# ============================================================
# Test 2: Single fork, two consumers
# ============================================================

def test_single_fork_two_consumers():
    """
    Source -> Fork -> Collector1
                   -> Collector2

    Each collector should get [0, 1, 2]
    """
    print("\n=== test_single_fork_two_consumers ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork = TracingFork(f.source, "fork")
        f.c1 = TracingCollector(f.fork, "c1")
        f.c2 = TracingCollector(f.fork, "c2")

    f.run_until_complete()

    r1 = f.c1.get_data()[0]
    r2 = f.c2.get_data()[0]
    print(f"c1 result: {r1}")
    print(f"c2 result: {r2}")
    assert r1 == [0, 1, 2]
    assert r2 == [0, 1, 2]


# ============================================================
# Test 3: Source -> two forks -> two collectors
# ============================================================

def test_source_two_forks_two_collectors():
    """
    Source -> Fork1 -> Collector1
           -> Fork2 -> Collector2

    Each collector should get [0, 1, 2]
    """
    print("\n=== test_source_two_forks_two_collectors ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork1 = TracingFork(f.source, "fork1")
        f.fork2 = TracingFork(f.source, "fork2")
        f.c1 = TracingCollector(f.fork1, "c1")
        f.c2 = TracingCollector(f.fork2, "c2")

    f.run_until_complete()

    r1 = f.c1.get_data()[0]
    r2 = f.c2.get_data()[0]
    print(f"c1 result: {r1}")
    print(f"c2 result: {r2}")
    assert r1 == [0, 1, 2]
    assert r2 == [0, 1, 2]


# ============================================================
# Test 4: Source -> two forks -> Join2
# ============================================================

def test_source_two_forks_join():
    """
    Source -> Fork1 -> Join2.a
           -> Fork2 -> Join2.b

    Join should get [0,1,2] from each fork, total = 6
    """
    print("\n=== test_source_two_forks_join ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork1 = TracingFork(f.source, "fork1")
        f.fork2 = TracingFork(f.source, "fork2")
        f.join = TracingJoin2(f.fork1, f.fork2, "join")

    f.run_until_complete()

    result = f.join.get_data()[0]
    print(f"Join result: {result}")
    assert result == 6, f"Expected 6, got {result}"


# ============================================================
# Test 5: Fork -> two forks -> two collectors (nested)
# ============================================================

def test_nested_fork_two_collectors():
    """
    Source -> Fork0 -> Fork0a -> Collector0a
                    -> Fork0b -> Collector0b

    Each collector should get [0, 1, 2]
    """
    print("\n=== test_nested_fork_two_collectors ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork0 = TracingFork(f.source, "fork0")
        f.fork0a = TracingFork(f.fork0, "fork0a")
        f.fork0b = TracingFork(f.fork0, "fork0b")
        f.c0a = TracingCollector(f.fork0a, "c0a")
        f.c0b = TracingCollector(f.fork0b, "c0b")

    f.run_until_complete()

    r0a = f.c0a.get_data()[0]
    r0b = f.c0b.get_data()[0]
    print(f"c0a result: {r0a}")
    print(f"c0b result: {r0b}")
    assert r0a == [0, 1, 2], f"c0a expected [0,1,2], got {r0a}"
    assert r0b == [0, 1, 2], f"c0b expected [0,1,2], got {r0b}"


# ============================================================
# Test 6: Fork -> two forks -> Join2 (THE FAILING PATTERN)
# ============================================================

def test_nested_fork_join():
    """
    Source -> Fork0 -> Fork0a -> Join.a
                    -> Fork0b -> Join.b

    Join should get [0,1,2] from each path, total = 6

    THIS IS THE MINIMAL FAILING PATTERN from the original test.
    """
    print("\n=== test_nested_fork_join ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork0 = TracingFork(f.source, "fork0")
        f.fork0a = TracingFork(f.fork0, "fork0a")
        f.fork0b = TracingFork(f.fork0, "fork0b")
        f.join = TracingJoin2(f.fork0a, f.fork0b, "join")

    f.run_until_complete()

    result = f.join.get_data()[0]
    print(f"Join result: {result}")
    assert result == 6, f"Expected 6, got {result}"


# ============================================================
# Test 7: Verify the fork receives correct data
# ============================================================

def test_fork_receives_correct_data():
    """
    Just verify that Fork0 receives exactly [0, 1, 2] from source.
    """
    print("\n=== test_fork_receives_correct_data ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork0 = TracingFork(f.source, "fork0")
        f.collector = TracingCollector(f.fork0, "coll")

    f.run_until_complete()

    result = f.collector.get_data()[0]
    print(f"Collector result: {result}")
    assert result == [0, 1, 2]


# ============================================================
# Test 8: Multiple consumers of same fork
# ============================================================

def test_fork_with_multiple_consumers():
    """
    Fork -> Collector1
         -> Collector2
         -> Collector3

    All three should get [0, 1, 2]
    """
    print("\n=== test_fork_with_multiple_consumers ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork = TracingFork(f.source, "fork")
        f.c1 = TracingCollector(f.fork, "c1")
        f.c2 = TracingCollector(f.fork, "c2")
        f.c3 = TracingCollector(f.fork, "c3")

    f.run_until_complete()

    r1 = f.c1.get_data()[0]
    r2 = f.c2.get_data()[0]
    r3 = f.c3.get_data()[0]
    print(f"c1: {r1}, c2: {r2}, c3: {r3}")
    assert r1 == [0, 1, 2]
    assert r2 == [0, 1, 2]
    assert r3 == [0, 1, 2]


# ============================================================
# Test 9: Simpler nested pattern without Join
# ============================================================

def test_nested_without_join():
    """
    Source -> Fork0 -> Fork0a -> Collector0a
           -> Fork1 -> Fork1a -> Collector1a

    Both collectors should get [0, 1, 2]
    """
    print("\n=== test_nested_without_join ===")

    with FlowHDL() as f:
        f.source = TracingSource("src")
        f.fork0 = TracingFork(f.source, "fork0")
        f.fork1 = TracingFork(f.source, "fork1")
        f.fork0a = TracingFork(f.fork0, "fork0a")
        f.fork1a = TracingFork(f.fork1, "fork1a")
        f.c0a = TracingCollector(f.fork0a, "c0a")
        f.c1a = TracingCollector(f.fork1a, "c1a")

    f.run_until_complete()

    r0a = f.c0a.get_data()[0]
    r1a = f.c1a.get_data()[0]
    print(f"c0a: {r0a}, c1a: {r1a}")
    assert r0a == [0, 1, 2]
    assert r1a == [0, 1, 2]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
