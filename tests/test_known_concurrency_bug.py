"""
KNOWN CONCURRENCY BUG: Binary tree streaming deadlock

This test exposes a deadlock in the concurrency system when using a binary tree
topology with streaming Fork/Join nodes.

ISSUE: The test hangs indefinitely (>2 minutes) and never completes.

TOPOLOGY:
- 1 Source node at the root
- 4 levels of binary Fork nodes (16 leaf nodes)
- 4 levels of binary Join nodes merging back to 1 final node
- Each Join node consumes two input streams sequentially

ROOT CAUSE HYPOTHESIS:
The Join nodes use sequential stream consumption:
    total = await consume_all(a_iter) + await consume_all(b_iter)

This creates implicit dependencies in the binary tree where:
- Each Join waits for stream A to complete before starting stream B
- In a tree topology, this can create circular wait conditions
- The generation-tracking fixes in Branch A don't detect/prevent this deadlock

POTENTIAL ISSUES:
1. Sequential stream consumption in Join creates ordering constraints
2. Multiple Join nodes at same level may be waiting on each other
3. Stream completion signals may not propagate correctly through tree
4. Barrier synchronization may deadlock when multiple consumers wait on same producer

This is the ONE configuration out of 8 large-scale stress tests that fails.
"""

import pytest
from flowno import node, FlowHDL, Stream
from flowno.core.event_loop.primitives import sleep


test_state = {}


def reset_test_state():
    test_state.clear()
    test_state['errors'] = []
    test_state['data'] = []
    test_state['completions'] = set()


class TestKnownConcurrencyBug:
    """Test that exposes known deadlock in binary tree streaming topology."""

    def setup_method(self):
        reset_test_state()

    def test_binary_tree_streaming_deadlock(self):
        """
        Binary tree: 1 source, 2 level-1 nodes, 4 level-2 nodes, etc.
        All streaming, culminating in one final gather.

        THIS TEST HANGS - DO NOT RUN WITHOUT SKIP MARKER
        """
        @node
        async def Source():
            for i in range(5):
                yield i

        @node(stream_in=["x"])
        async def Fork(x: Stream[int]):
            async for val in x:
                yield val

        @node(stream_in=["a", "b"])
        async def Join(a: Stream[int], b: Stream[int]):
            total = 0
            a_iter = a.__aiter__()
            b_iter = b.__aiter__()

            async def consume_all(it):
                s = 0
                try:
                    while True:
                        s += await it.__anext__()
                except StopAsyncIteration:
                    pass
                return s

            # PROBLEM: Sequential consumption of streams
            # This creates ordering constraints that may deadlock in tree topology
            total = await consume_all(a_iter) + await consume_all(b_iter)
            return total

        with FlowHDL() as f:
            # Level 0: 1 source
            f.n_0_0 = Source()

            # Build binary tree: Fork nodes fan out
            # Level 1: 2 nodes
            for i in range(2):
                exec(f"f.n_1_{i} = Fork(f.n_0_0)")

            # Level 2: 4 nodes
            for i in range(4):
                parent = i // 2
                exec(f"f.n_2_{i} = Fork(f.n_1_{parent})")

            # Level 3: 8 nodes
            for i in range(8):
                parent = i // 2
                exec(f"f.n_3_{i} = Fork(f.n_2_{parent})")

            # Level 4: 16 nodes
            for i in range(16):
                parent = i // 2
                exec(f"f.n_4_{i} = Fork(f.n_3_{parent})")

            # Now join back: Join nodes merge pairs
            # Level 5: 8 Join nodes (16 → 8)
            for i in range(8):
                left = i * 2
                right = i * 2 + 1
                exec(f"f.j_5_{i} = Join(f.n_4_{left}, f.n_4_{right})")

            # Level 6: 4 Join nodes (8 → 4)
            for i in range(4):
                left = i * 2
                right = i * 2 + 1
                exec(f"f.j_6_{i} = Join(f.j_5_{left}, f.j_5_{right})")

            # Level 7: 2 Join nodes (4 → 2)
            for i in range(2):
                left = i * 2
                right = i * 2 + 1
                exec(f"f.j_7_{i} = Join(f.j_6_{left}, f.j_6_{right})")

            # Final join: 1 node (2 → 1)
            exec("f.final = Join(f.j_7_0, f.j_7_1)")

        try:
            f.run_until_complete(_debug_max_wait_time=20)
        except Exception as e:
            test_state['errors'].append(f'Exception: {e}')

        # Should complete without errors (but it won't - it hangs)
        assert len(test_state['errors']) == 0, \
            f"Errors: {test_state['errors']}"
