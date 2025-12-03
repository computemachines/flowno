"""
Flowno Simple Streaming Deadlock - Minimal Reproduction

Bug: With simplified streaming logic, consumer can't read second stream value.

This is a 2-node linear graph:
  - Node A (Producer): yields stream of strings
  - Node B (Consumer): consumes stream, returns accumulated result

Sequence:
  1. A yields "hello"
  2. B consumes "hello"
  3. A yields "world"
  4. BUG: B can't read "world" → deadlock
"""

import os
import signal
import sys
import threading
import time
from collections.abc import AsyncGenerator
from typing import Union

from flowno import FlowHDL, Stream, node, sleep, exit as flowno_exit

# Configuration
DEBUG = True
TOKEN_DELAY = 0.3  # seconds between tokens
TIMEOUT_SECONDS = 10.0  # hard kill timeout

# Global state
TOKENS_CONSUMED = []


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

@node
async def Producer() -> AsyncGenerator[str, None]:
    """
    Yields a stream of 3 tokens.
    """
    dlog("PRODUCER", "=== STARTED ===")

    tokens = ["hello", "world", "test"]
    for i, token in enumerate(tokens):
        dlog("PRODUCER", f"  yielding token {i+1}/3: '{token}'")
        yield token
        if i < len(tokens) - 1 and TOKEN_DELAY > 0:
            await sleep(TOKEN_DELAY)

    dlog("PRODUCER", "=== COMPLETED ===")


@node(stream_in=["input_stream"])
async def Consumer(input_stream: Union[Stream[str], None] = None) -> str:
    """
    Consumes stream and accumulates tokens.
    """
    dlog("CONSUMER", "=== STARTED ===")

    accumulator = ""
    if input_stream is not None:
        dlog("CONSUMER", "  consuming stream...")
        token_count = 0

        async for token in input_stream:
            token_count += 1
            TOKENS_CONSUMED.append(token)
            dlog("CONSUMER", f"  got token #{token_count}: '{token}'")
            accumulator = token.upper() + " " + accumulator

        dlog("CONSUMER", f"  stream consumption done ({token_count} tokens)")
    else:
        dlog("CONSUMER", "  no stream provided")

    result = accumulator.strip()
    dlog("CONSUMER", f"=== RETURNING: '{result}' ===")
    return result


# =============================================================================
# Test Harness
# =============================================================================

async def monitor_progress(event_loop):
    """
    Monitor test progress and detect deadlock.
    """
    dlog("MONITOR", "Starting monitoring task...")

    # Wait for execution to start
    await sleep(1.0)

    # Monitor for 5 seconds
    for i in range(10):
        await sleep(0.5)
        dlog("MONITOR", f"Tokens consumed so far: {len(TOKENS_CONSUMED)} - {TOKENS_CONSUMED}")

    # Check result
    if len(TOKENS_CONSUMED) < 3:
        dlog("MONITOR", "="*60)
        dlog("MONITOR", "DEADLOCK DETECTED!")
        dlog("MONITOR", f"  Only consumed {len(TOKENS_CONSUMED)}/3 tokens: {TOKENS_CONSUMED}")
        dlog("MONITOR", f"  Consumer got stuck after: {TOKENS_CONSUMED[-1] if TOKENS_CONSUMED else 'nothing'}")
        dlog("MONITOR", "="*60)
    else:
        dlog("MONITOR", f"Success - consumed all {len(TOKENS_CONSUMED)} tokens")

    # Exit the event loop
    await flowno_exit()


def main():
    """Entry point for the simple streaming deadlock test."""
    print("="*60)
    print("Flowno Simple Streaming Deadlock Test")
    print("="*60)
    print()
    print("Graph: Producer --> Consumer")
    print("       (stream)    (accumulator)")
    print()
    print("Test: Producer yields 3 tokens, consumer should receive all")
    print(f"Timeout: {TIMEOUT_SECONDS}s (hard kill)")
    print()

    # Install hard kill timeout
    cancel_timeout = install_sigkill_timeout(TIMEOUT_SECONDS)

    try:
        # Build the graph
        with FlowHDL() as f:
            f.producer = Producer()
            f.consumer = Consumer(f.producer)

        # Schedule the monitor task
        f._flow.event_loop.create_task(monitor_progress(f._flow.event_loop))

        print("Running flow...")
        print()

        # Run until completion (or deadlock timeout)
        f.run_until_complete(terminate_on_node_error=True)

    finally:
        # Cancel the timeout if we exit normally
        cancel_timeout()

    print()
    print("Done!")

    # Exit with error code if deadlock was detected
    if len(TOKENS_CONSUMED) < 3:
        print(f"\nFAILED: Only consumed {len(TOKENS_CONSUMED)}/3 tokens")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: Consumed all {len(TOKENS_CONSUMED)} tokens")


if __name__ == "__main__":
    main()
