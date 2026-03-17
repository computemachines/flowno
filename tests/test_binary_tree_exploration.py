"""
Exploration of binary tree streaming topology to find minimal failing configuration.

Two dimensions to explore:
1. Depth (number of fork/join levels)
2. Branching factor (fan-out count per node)

Starting from the failing 4-level binary tree and reducing until it passes.
"""

import pytest
from flowno import node, FlowHDL, Stream


# ============================================================
# Shared node definitions
# ============================================================

@node
async def Source():
    """Single source that yields integers."""
    for i in range(3):
        yield i


@node(stream_in=["x"])
async def Fork(x: Stream[int]):
    """Pass-through streaming node (fan-out)."""
    async for val in x:
        yield val


@node(stream_in=["a", "b"])
async def Join2(a: Stream[int], b: Stream[int]):
    """Join two streams by summing all values."""
    total = 0
    async for val in a:
        total += val
    async for val in b:
        total += val
    return total


@node(stream_in=["a"])
async def Join1(a: Stream[int]):
    """Join single stream (identity aggregation)."""
    total = 0
    async for val in a:
        total += val
    return total


# ============================================================
# Minimal tests - single level
# ============================================================

class TestSingleLevel:
    """Tests with just one fork level and one join level."""

    def test_source_to_join1_direct(self):
        """Source -> Join1 (single stream, no fork)"""
        with FlowHDL() as f:
            f.source = Source()
            f.join = Join1(f.source)

        f.run_until_complete()
        # 0 + 1 + 2 = 3
        assert f.join.get_data() == (3,)

    def test_source_fork1_join1(self):
        """Source -> Fork -> Join1"""
        with FlowHDL() as f:
            f.source = Source()
            f.fork = Fork(f.source)
            f.join = Join1(f.fork)

        f.run_until_complete()
        assert f.join.get_data() == (3,)

    def test_source_fork2_join2(self):
        """
        Source -> Fork0, Fork1 -> Join2

        Two forks from same source, joined together.
        """
        with FlowHDL() as f:
            f.source = Source()
            f.fork0 = Fork(f.source)
            f.fork1 = Fork(f.source)
            f.join = Join2(f.fork0, f.fork1)

        f.run_until_complete()
        # Each fork gets 0+1+2=3, joined = 3+3=6
        assert f.join.get_data() == (6,)


# ============================================================
# Two-level tests
# ============================================================

class TestTwoLevels:
    """Tests with two fork levels and two join levels."""

    def test_depth2_width2(self):
        """
        Depth 2, width 2 (binary tree)

              Source
              /    \
           Fork0  Fork1
            |       |
           Fork2  Fork3
             \     /
              Join0
        """
        with FlowHDL() as f:
            # Level 0: Source
            f.source = Source()

            # Level 1: 2 forks from source
            f.fork_1_0 = Fork(f.source)
            f.fork_1_1 = Fork(f.source)

            # Level 2: Each level-1 fork feeds one level-2 fork
            f.fork_2_0 = Fork(f.fork_1_0)
            f.fork_2_1 = Fork(f.fork_1_1)

            # Join level: Merge the two level-2 forks
            f.join = Join2(f.fork_2_0, f.fork_2_1)

        f.run_until_complete()
        assert f.join.get_data() == (6,)

    def test_depth2_width2_with_join_levels(self):
        """
        Depth 2, width 2 with matching join levels

              Source
              /    \
           Fork0  Fork1
           /   \  /   \
         F2   F3 F4   F5
          \   /   \   /
          Join0   Join1
             \    /
             FinalJoin
        """
        with FlowHDL() as f:
            # Level 0: Source
            f.source = Source()

            # Fork level 1: 2 forks from source
            f.f1_0 = Fork(f.source)
            f.f1_1 = Fork(f.source)

            # Fork level 2: 4 forks (2 from each level-1)
            f.f2_0 = Fork(f.f1_0)
            f.f2_1 = Fork(f.f1_0)
            f.f2_2 = Fork(f.f1_1)
            f.f2_3 = Fork(f.f1_1)

            # Join level 1: 2 joins (merge pairs)
            f.j1_0 = Join2(f.f2_0, f.f2_1)
            f.j1_1 = Join2(f.f2_2, f.f2_3)

            # Final join - BUT these are not streams anymore!
            # Join2 returns int, not Stream[int]
            # This won't work with Join2...

        # This test structure is flawed - Join2 returns int, not Stream
        # Skip for now
        pytest.skip("Join2 returns int, can't chain joins this way")


# ============================================================
# Exploring the exact failing configuration
# ============================================================

class TestOriginalFailingPattern:
    """
    Recreate the original failing pattern at smaller scale.

    The original test used exec() to dynamically create nodes.
    Let's do it explicitly to understand the structure.
    """

    def test_minimal_fork_join_tree_depth1(self):
        """
        Minimal: 1 source, 2 forks, 1 join

        Source -> Fork0, Fork1 -> Join
        """
        with FlowHDL() as f:
            f.source = Source()
            f.f0 = Fork(f.source)
            f.f1 = Fork(f.source)
            f.join = Join2(f.f0, f.f1)

        f.run_until_complete()
        assert f.join.get_data() == (6,)

    def test_fork_chain_then_join(self):
        """
        Source -> Fork -> Fork -> Fork -> Join1

        Linear chain, no branching.
        """
        with FlowHDL() as f:
            f.source = Source()
            f.f1 = Fork(f.source)
            f.f2 = Fork(f.f1)
            f.f3 = Fork(f.f2)
            f.join = Join1(f.f3)

        f.run_until_complete()
        assert f.join.get_data() == (3,)

    def test_diamond_pattern(self):
        """
        Diamond: Source -> Fork0, Fork1 -> Join2

        This is the same as test_minimal_fork_join_tree_depth1
        but named explicitly as diamond.
        """
        with FlowHDL() as f:
            f.source = Source()
            f.left = Fork(f.source)
            f.right = Fork(f.source)
            f.join = Join2(f.left, f.right)

        f.run_until_complete()
        assert f.join.get_data() == (6,)

    def test_nested_diamond(self):
        """
        Nested diamond pattern:

                Source
               /      \
            Fork0    Fork1
            /   \    /   \
          F0a  F0b  F1a  F1b
           \   /     \   /
           Join0     Join1

        Note: Join0 and Join1 are terminal (return int, not stream)
        """
        with FlowHDL() as f:
            f.source = Source()

            # First split
            f.fork0 = Fork(f.source)
            f.fork1 = Fork(f.source)

            # Second split (from fork0)
            f.f0a = Fork(f.fork0)
            f.f0b = Fork(f.fork0)

            # Second split (from fork1)
            f.f1a = Fork(f.fork1)
            f.f1b = Fork(f.fork1)

            # Join pairs
            f.join0 = Join2(f.f0a, f.f0b)
            f.join1 = Join2(f.f1a, f.f1b)

        f.run_until_complete()
        # Each source value (0,1,2) goes through 4 paths total
        # join0 gets: f0a (0,1,2) + f0b (0,1,2) = 6
        # join1 gets: f1a (0,1,2) + f1b (0,1,2) = 6
        assert f.join0.get_data() == (6,)
        assert f.join1.get_data() == (6,)


# ============================================================
# Recreating the original failing test at reduced scale
# ============================================================

class TestScaledDownOriginal:
    """
    The original test had:
    - 4 levels of forks (1->2->4->8->16 nodes)
    - 4 levels of joins (16->8->4->2->1 nodes)

    Let's try smaller versions.
    """

    def test_1_fork_level_1_join_level(self):
        """
        1 fork level (1->2), 1 join level (2->1)

        Source -> Fork0, Fork1 -> Join
        """
        with FlowHDL() as f:
            f.source = Source()
            f.f0 = Fork(f.source)
            f.f1 = Fork(f.source)
            f.join = Join2(f.f0, f.f1)

        f.run_until_complete()
        assert f.join.get_data() == (6,)

    def test_2_fork_levels_1_join_level(self):
        """
        2 fork levels (1->2->4), 1 join level (need 2 joins for 4 inputs)

                Source
               /      \
            Fork0    Fork1
            /   \    /   \
          F0a  F0b  F1a  F1b
           \   /     \   /
           Join0     Join1
        """
        with FlowHDL() as f:
            f.source = Source()

            # Fork level 1
            f.f0 = Fork(f.source)
            f.f1 = Fork(f.source)

            # Fork level 2
            f.f0a = Fork(f.f0)
            f.f0b = Fork(f.f0)
            f.f1a = Fork(f.f1)
            f.f1b = Fork(f.f1)

            # Join level 1 (4->2)
            f.j0 = Join2(f.f0a, f.f0b)
            f.j1 = Join2(f.f1a, f.f1b)

        f.run_until_complete()
        assert f.j0.get_data() == (6,)
        assert f.j1.get_data() == (6,)

    def test_2_fork_levels_2_join_levels(self):
        """
        2 fork levels, 2 join levels

        This requires chaining joins, but Join2 returns int not Stream.
        We need a streaming join to chain them.
        """
        pytest.skip("Need streaming Join to chain join levels")

    def test_3_fork_levels_no_join(self):
        """
        Just test that 3 fork levels work without joining.

        Source -> 2 forks -> 4 forks -> 8 forks (all terminal)
        """
        results = []

        @node(stream_in=["x"])
        async def TerminalConsumer(x: Stream[int]):
            total = 0
            async for val in x:
                total += val
            results.append(total)
            return total

        with FlowHDL() as f:
            f.source = Source()

            # Fork level 1 (2 nodes)
            f.f1_0 = Fork(f.source)
            f.f1_1 = Fork(f.source)

            # Fork level 2 (4 nodes)
            f.f2_0 = Fork(f.f1_0)
            f.f2_1 = Fork(f.f1_0)
            f.f2_2 = Fork(f.f1_1)
            f.f2_3 = Fork(f.f1_1)

            # Fork level 3 (8 nodes)
            f.f3_0 = Fork(f.f2_0)
            f.f3_1 = Fork(f.f2_0)
            f.f3_2 = Fork(f.f2_1)
            f.f3_3 = Fork(f.f2_1)
            f.f3_4 = Fork(f.f2_2)
            f.f3_5 = Fork(f.f2_2)
            f.f3_6 = Fork(f.f2_3)
            f.f3_7 = Fork(f.f2_3)

            # Terminal consumers for each level-3 fork
            f.t0 = TerminalConsumer(f.f3_0)
            f.t1 = TerminalConsumer(f.f3_1)
            f.t2 = TerminalConsumer(f.f3_2)
            f.t3 = TerminalConsumer(f.f3_3)
            f.t4 = TerminalConsumer(f.f3_4)
            f.t5 = TerminalConsumer(f.f3_5)
            f.t6 = TerminalConsumer(f.f3_6)
            f.t7 = TerminalConsumer(f.f3_7)

        f.run_until_complete()
        # Each terminal should get 0+1+2=3
        assert all(r == 3 for r in results), f"Results: {results}"


# ============================================================
# The key difference: Join with TWO streaming inputs
# ============================================================

class TestJoinWithTwoStreamInputs:
    """
    The failing test has Join nodes with TWO streaming inputs.
    Let's isolate this pattern.
    """

    def test_join2_from_same_source(self):
        """Two streams from same source -> Join2"""
        with FlowHDL() as f:
            f.source = Source()
            f.join = Join2(f.source, f.source)

        f.run_until_complete()
        # Both inputs read same source
        assert f.join.get_data() == (6,)

    def test_join2_from_forked_source(self):
        """Source forked twice -> Join2"""
        with FlowHDL() as f:
            f.source = Source()
            f.left = Fork(f.source)
            f.right = Fork(f.source)
            f.join = Join2(f.left, f.right)

        f.run_until_complete()
        assert f.join.get_data() == (6,)

    def test_join2_with_longer_left_path(self):
        """
        Left path has more forks than right:

        Source -> Fork -> Fork -> Join2.a
        Source -> Fork ----------> Join2.b
        """
        with FlowHDL() as f:
            f.source = Source()

            # Left path (2 forks)
            f.left1 = Fork(f.source)
            f.left2 = Fork(f.left1)

            # Right path (1 fork)
            f.right1 = Fork(f.source)

            f.join = Join2(f.left2, f.right1)

        f.run_until_complete()
        assert f.join.get_data() == (6,)

    def test_multiple_join2_same_level(self):
        """
        Multiple Join2 nodes at same level, all fed by forks from same source.

        Source -> Fork0, Fork1, Fork2, Fork3
                   \    /        \    /
                   Join0         Join1
        """
        with FlowHDL() as f:
            f.source = Source()
            f.f0 = Fork(f.source)
            f.f1 = Fork(f.source)
            f.f2 = Fork(f.source)
            f.f3 = Fork(f.source)
            f.j0 = Join2(f.f0, f.f1)
            f.j1 = Join2(f.f2, f.f3)

        f.run_until_complete()
        assert f.j0.get_data() == (6,)
        assert f.j1.get_data() == (6,)

    def test_many_join2_same_level(self):
        """
        8 Join2 nodes at same level (simulating the failing test's join level 5)

        Source -> 16 Forks -> 8 Join2 nodes
        """
        with FlowHDL() as f:
            f.source = Source()

            # 16 forks from source
            for i in range(16):
                setattr(f, f'f{i}', Fork(f.source))

            # 8 joins pairing adjacent forks
            for i in range(8):
                left = getattr(f, f'f{i*2}')
                right = getattr(f, f'f{i*2+1}')
                setattr(f, f'j{i}', Join2(left, right))

        f.run_until_complete()
        for i in range(8):
            j = getattr(f, f'j{i}')
            assert j.get_data() == (6,), f"j{i} failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
