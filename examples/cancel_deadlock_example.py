"""
Flowno Stream Cancellation Deadlock - Minimal Reproduction

Bug: After a node calls `await stream.cancel()` and returns a new value,
the upstream stream-producing node is never scheduled for the next iteration.

This is a 2-node circular graph:
  - Node A: consumes stream (optional), returns int
  - Node B: takes int, yields stream

Sequence:
  1. A returns 1 (no stream on first iteration)
  2. B starts with 1, yields tokens
  3. A consumes tokens, sets cancel flag, calls stream.cancel(), returns 2
  4. BUG: B never starts with input 2 → deadlock
"""

import os
import signal
import sys
import threading
import time
from collections.abc import AsyncGenerator

from flowno import AsyncQueue, FlowHDL, Stream, node, sleep, exit as flowno_exit

# Configuration
DEBUG = True
TOKEN_DELAY = 0.3  # seconds between tokens
TIMEOUT_SECONDS = 10.0  # hard kill timeout

# Global state for test control
CANCEL_FLAG = [False]
ITERATION_COUNT = [0]


def dlog(tag: str, msg: str):
    """Debug logging with timestamp."""
    if DEBUG:
        ts = time.strftime("%H:%M:%S")
        print(f"[{tag}] {ts} {msg}", flush=True)


def install_sigkill_timeout(seconds: float = TIMEOUT_SECONDS):
    """Arm a hard kill timer so the test cannot hang indefinitely."""

    def _terminate() -> None:
        print(f"\n{'='*60}", flush=True)
        print(f"TIMEOUT ({seconds:.1f}s) exceeded - sending SIGKILL/SIGTERM", flush=True)
        print(f"{'='*60}\n", flush=True)
        sig = getattr(signal, "SIGKILL", None) or getattr(signal, "SIGTERM", None)
        if sig is not None:
            os.kill(os.getpid(), sig)
        else:
            os._exit(137)

    timer = threading.Timer(seconds, _terminate)
    timer.daemon = True
    timer.start()
    return timer.cancel


# =============================================================================
# Minimal Nodes
# =============================================================================

@node(stream_in=["input_stream"])
async def StreamIn_Out(
    cancel_ref: list[bool],
    input_stream: Stream[str] | None = None,
) -> int:
    """
    Consumes an optional stream, returns an incrementing int.
    
    On each iteration:
    - If stream exists, consume it (cancel mid-stream if flag set)
    - Increment and return counter
    """
    global ITERATION_COUNT
    
    dlog("SI_MO", "=== ENTERED ===")
    
    if input_stream:
        dlog("SI_MO", "  consuming stream...")
        token_count = 0
        async for item in input_stream:
            token_count += 1
            dlog("SI_MO", f"  got token #{token_count}: {item}")
            
            # Cancel after receiving some tokens
            if cancel_ref[0]:
                dlog("SI_MO", "  >>> CANCEL FLAG SET, calling stream.cancel()")
                await input_stream.cancel()
                dlog("SI_MO", "  >>> cancel() returned, exiting stream loop")
                break
        dlog("SI_MO", f"  stream consumption done ({token_count} tokens)")
    else:
        dlog("SI_MO", "  no stream (first iteration)")
    
    # Reset cancel flag
    cancel_ref[0] = False
    
    # Increment and return
    ITERATION_COUNT[0] += 1
    result = ITERATION_COUNT[0]
    dlog("SI_MO", f"=== RETURNING: {result} ===")
    return result


@node
async def MonoIn_Stream(input_int: int) -> AsyncGenerator[str, None]:
    """
    Takes an int, yields a stream of tokens.
    """
    dlog("MI_SO", f"=== ENTERED with input: {input_int} ===")
    
    for i in range(1, 11):  # 10 tokens
        dlog("MI_SO", f"  yielding token{i}")
        yield f"token{i}"
        if i < 10 and TOKEN_DELAY > 0:
            await sleep(TOKEN_DELAY)
    
    dlog("MI_SO", "=== COMPLETED ===")


# =============================================================================
# Test Harness
# =============================================================================

async def run_test(event_loop):
    """
    Test sequence:
    1. Wait for first iteration to start streaming
    2. Set cancel flag
    3. Wait to see if second iteration runs
    4. If no second iteration → deadlock detected
    """
    dlog("TEST", "Starting test sequence...")
    
    # Wait for first stream to start
    dlog("TEST", "Step 1: Waiting 1s for first stream...")
    await sleep(1.0)
    
    # Set cancel flag
    dlog("TEST", "Step 2: Setting cancel flag")
    CANCEL_FLAG[0] = True
    
    # Wait a bit for cancellation to process
    await sleep(0.5)
    
    # Check if we got past iteration 1
    dlog("TEST", f"Step 3: Current iteration count = {ITERATION_COUNT[0]}")
    
    # Wait to see if second iteration runs
    dlog("TEST", "Step 4: Waiting 5s for second iteration...")
    initial_count = ITERATION_COUNT[0]
    await sleep(5.0)
    
    # Check result
    if ITERATION_COUNT[0] == initial_count:
        dlog("TEST", "="*60)
        dlog("TEST", "DEADLOCK DETECTED!")
        dlog("TEST", f"  Stuck at iteration: {ITERATION_COUNT[0]}")
        dlog("TEST", "  MonoIn_Stream never started for iteration 2")
        dlog("TEST", "="*60)
    else:
        dlog("TEST", f"No deadlock - reached iteration {ITERATION_COUNT[0]}")
    
    # Exit the event loop
    await flowno_exit()


def main():
    """Entry point for the deadlock test."""
    print("="*60)
    print("Flowno Stream Cancellation Deadlock Test")
    print("="*60)
    print()
    print("Graph: StreamIn_Out <---> MonoIn_Stream")
    print("       (int out)         (stream out)")
    print()
    print("Test: Cancel stream mid-iteration, check if next iteration runs")
    print(f"Timeout: {TIMEOUT_SECONDS}s (hard kill)")
    print()
    
    # Install hard kill timeout
    cancel_timeout = install_sigkill_timeout(TIMEOUT_SECONDS)
    
    try:
        # Build the graph
        with FlowHDL() as f:
            # Circular dependency: A consumes B's stream, B consumes A's output
            f.node_a = StreamIn_Out(CANCEL_FLAG, f.node_b)
            f.node_b = MonoIn_Stream(f.node_a)
        
        # Schedule the test task
        f._flow.event_loop.create_task(run_test(f._flow.event_loop))
        
        print("Running flow...")
        print()
        
        # Run until completion (or deadlock timeout)
        f.run_until_complete()
        
    finally:
        # Cancel the timeout if we exit normally
        cancel_timeout()
    
    print()
    print("Done!")
    
    # Exit with error code if deadlock was detected
    if ITERATION_COUNT[0] < 2:
        sys.exit(1)


if __name__ == "__main__":
    main()
