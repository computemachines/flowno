#!/usr/bin/env python
"""
Simple Cyclic Flow Example

This example demonstrates a cyclic dataflow in Flowno. It shows:
  - How the @node decorator transforms async functions into Node classes.
  - That nodes are re-executed as their inputs change, even in a cycle.
  - The importance of using non-blocking primitives (e.g. flowno.sleep instead of time.sleep or asyncio.sleep).
  - How to terminate a cyclic flow by raising an exception.

Key Lessons and Warnings:
  1. The @node decorator turns your async functions into special Node classes.
  2. In cyclic flows, nodes run repeatedly until a termination condition is met.
  3. Do not call blocking functions like time.sleep; use flowno.sleep() to yield control.
  4. The order of node instantiation inside FlowHDL does not matter due to placeholder magic.
  5. Raising an uncaught exception in any node will propagate and terminate the entire flow.
"""

from time import time

from flowno import FlowHDL, node, sleep
from flowno.core.event_loop.instrumentation import (
    LogInstrument as EventLoopLogInstrument,
)
from flowno.core.event_loop.types import DeltaTime
from flowno.core.flow.instrumentation import LogInstrument as FlowLogInstrument


# Custom exception to signal termination of the cyclic flow.
class TerminateFlow(Exception):
    pass


@node
async def Sum(x: int = 0, y: int = 0) -> int:
    """
    Sums its two inputs. This node demonstrates how each invocation is re-run
    as part of the cyclic dataflow. Once x reaches a threshold (x >= 3), it raises
    an exception to stop the cycle.

    Note:
      - Every time the flow iterates, Sum is called with fresh inputs.
      - The debug prints help you trace the cycle's execution.
    """
    print(f"[Sum] Called with x={x}, y={y}")
    if x >= 3:
        print("[Sum] x is greater than or equal to 3, terminating the flow")
        # Propagating this exception stops the flow.
        raise TerminateFlow()
    return x + y


@node
async def IncrementAndSleep(x: int, delay: DeltaTime):
    """
    Increments the input value by 1 after a delay.

    Warnings:
      - Avoid using time.sleep(): It blocks the entire event loop.
      - Do not use asyncio.sleep(): Flowno uses its own event loop.
      - Instead, use flowno.sleep(), which delays only this node and allows other tasks to run.
    """
    print(f"[IncrementAndSleep] Called with x={x}, delay={delay}")
    # Delay using flowno.sleep() so that only this node is suspended.
    actual_delay = await sleep(delay)
    print(f"[IncrementAndSleep] Desired delay: {delay}, actual delay: {actual_delay}")
    return x + 1


def main():
    """
    Constructs and executes a doubly cyclic flow where:

    f.inc_node_a.output(0) -> f.sum_node.input(0)
    f.inc_node_b.output(0) -> f.sum_node.input(1)
    f.sum_node.output(0) -> f.inc_node_a.input(0)
    f.sum_node.output(0) -> f.inc_node_b.input(0)

    - The Sum node receives input from two IncrementAndSleep nodes.
    - Both IncrementAndSleep nodes use Sum's output as their input.

    This cycle runs continuously until the Sum node detects that its x value
    has reached or exceeded the threshold (>= 3), at which point it raises TerminateFlow.
    """
    with FlowHDL() as f:
        # Nodes can be connected out-of-order. The placeholders allow us to reference
        # nodes (like f.sum_node) before they are fully defined.
        f.sum_node = Sum(f.inc_node_a, f.inc_node_b)
        f.inc_node_a = IncrementAndSleep(f.sum_node, 1.5)
        f.inc_node_b = IncrementAndSleep(f.sum_node, 2.1)

    start_time = time()
    try:
        f.run_until_complete()
    except TerminateFlow:
        print("Flow was terminated as expected when Sum reached the threshold.")
    else:
        print("Flow completed without triggering the termination condition.")
    duration = time() - start_time
    print(f"Total Time: {duration}")


if __name__ == "__main__":
    main()
