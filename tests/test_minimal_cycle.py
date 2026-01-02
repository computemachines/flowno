"""Minimal test to reproduce streaming cycle failures.

The issue: When running a streaming cycle past generation 0, the second
streamed value is lost.

Log analysis shows:
- First StreamCheckCommand returns Some(value='a') ✓
- Second StreamCheckCommand throws StopAsyncIteration ✗

ROOT CAUSE (found via debug logging):
In StreamCheckCommand handler, section 4 checks for stream completion:
    completion_marker = clip_generation(desired_generation, 0)
    if completion_marker in producer_node._data:
        throw StopAsyncIteration

For desired_generation=(1, 1):
- clip_generation((1, 1), 0) returns (0,) instead of (1,)
  because clip_generation finds the highest gen that is <= input,
  and (1,) > (1, 1) in generation ordering (shorter = more final)
- (0,) IS in producer._data (from gen 0's completion)
- So StopAsyncIteration is thrown prematurely

The fix: Use simple truncation (gen[:1]) instead of clip_generation
to get the parent generation for completion checking.
"""
import logging
from typing import TypeVar

from flowno import FlowHDL, Stream, node
from flowno.core.flow.flow import TerminateLimitReached
from pytest import raises

logger = logging.getLogger(__name__)

T = TypeVar("T")


@node
async def StreamTwo(input: list[str] | None = None):
    """Stream two values. If input is None, stream ['a', 'b']."""
    if input is None:
        input = ["a", "b"]
    for i, word in enumerate(input):
        logger.info(f"StreamTwo yielding [{i}]: {word}")
        yield word
    logger.info(f"StreamTwo finished yielding all {len(input)} values")


@node(stream_in=["stream"])
async def Collect(stream: Stream[T]) -> list[T]:
    """Collect all stream values into a list (in order)."""
    result: list[T] = []
    count = 0
    async for word in stream:
        logger.info(f"Collect received [{count}]: {word}")
        result.append(word)
        count += 1
    logger.info(f"Collect finished with {count} items: {result}")
    return result


def test_cycle_generation_0():
    """Generation 0 should work - no prior cycle data."""
    with FlowHDL() as f:
        f.stream = StreamTwo(f.collect)
        f.collect = Collect(f.stream)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.collect: (0,)})

    # Input was None -> streamed ['a', 'b'] -> collected ['a', 'b']
    assert f.collect.get_data() == (["a", "b"],)


def test_cycle_generation_1():
    """Generation 1 fails - second streamed value is lost.

    Timeline:
    - Gen 0: StreamTwo yields 'a', 'b' -> Collect returns ['a', 'b']
    - Gen 1: StreamTwo should yield 'a', 'b' again (from gen 0 output)
             But Collect only receives 'a', then stream closes prematurely
    """
    with FlowHDL() as f:
        f.stream = StreamTwo(f.collect)
        f.collect = Collect(f.stream)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.collect: (1,)})

    # Should get ['a', 'b'] but only gets ['a'] due to the bug
    assert f.collect.get_data() == (["a", "b"],)

@node
async def StreamTwo_NoDefault(input: list[str]):
    """Stream two values from input list."""
    for i, word in enumerate(input):
        logger.info(f"StreamTwo_NoDefault yielding [{i}]: {word}")
        yield word
    logger.info(f"StreamTwo_NoDefault finished yielding all {len(input)} values")

@node(stream_in=["stream"])
async def Collect_WithDefault(stream: Stream[T] | None = None) -> list[T]:
    """Collect all stream values into a list (in order).

    If stream is None, return ["a", "b"] (two items to match StreamTwo's output).
    """
    if stream is None:
        return ["a", "b"]
    result: list[T] = []
    count = 0
    async for word in stream:
        logger.info(f"Collect_WithDefault received [{count}]: {word}")
        result.append(word)
        count += 1
    logger.info(f"Collect_WithDefault finished with {count} items: {result}")
    return result

def test_cycle_generation_0_swapped_defaults():
    """Generation 0 with swapped defaults - stitch is on the streaming edge.

    Topology: StreamTwo_NoDefault -> Collect_WithDefault -> back to StreamTwo_NoDefault

    Key difference from original:
    - Original: default on mono edge (Collect -> StreamTwo), stitch_level_0=1 on mono edge
    - Swapped: default on streaming edge (StreamTwo -> Collect), stitch_level_0=1 on streaming edge

    Gen 0 timeline:
    - Collect_WithDefault's streaming input has no data, uses default (None) -> returns ["ab"]
    - StreamTwo_NoDefault's input sees Collect at (0,), runs with ["ab"] -> yields 'a', 'b'
    - But Collect already finished gen 0 with default, won't re-run

    Expected: Collect at gen 0 returns ["ab"] (from default, not from stream)
    """
    with FlowHDL() as f:
        f.stream = StreamTwo_NoDefault(f.collect)
        f.collect = Collect_WithDefault(f.stream)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.collect: (0,)})

    # Collect used default (stream=None) -> returned ["a", "b"]
    assert f.collect.get_data() == (["a", "b"],)


def test_cycle_generation_1_swapped_defaults():
    """Generation 1 with swapped defaults - stitch is on the streaming edge.

    This tests whether the StreamCheckCommand correctly handles stitch values
    on streaming edges.

    Gen 0:
    - Collect uses default -> ["ab"]
    - StreamTwo gets ["ab"], yields 'a', 'b'

    Gen 1:
    - Collect should now consume StreamTwo's actual stream (from gen 0)
    - StreamTwo at gen 0 yielded 'a', 'b' -> Collect should collect ['a', 'b']
    - BUT: the streaming edge has stitch_level_0=1, which may affect the
      stream completion/reset detection logic

    Expected: Collect at gen 1 has ['a', 'b'] (collected from StreamTwo's gen 0 stream)

    If this fails similarly to test_cycle_generation_1, it confirms that
    the fix needs to incorporate stitch values in the StreamCheckCommand logic.
    """
    with FlowHDL() as f:
        f.stream = StreamTwo_NoDefault(f.collect)
        f.collect = Collect_WithDefault(f.stream)

    with raises(TerminateLimitReached):
        f.run_until_complete(stop_at_node_generation={f.collect: (1,)})

    # Gen 1: Collect should consume StreamTwo's stream from gen 0
    # StreamTwo at gen 0 yielded 'a', 'b' (from Collect's default ["a", "b"])
    # So Collect should collect ['a', 'b']
    assert f.collect.get_data() == (["a", "b"],)