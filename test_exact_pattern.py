"""Match the exact pattern from the failing test."""

from flowno import FlowHDL, Stream, node
from flowno.core.event_loop.primitives import sleep

consumer1_chunks = []
consumer2_chunks = []

@node
async def ThreeChunkSource():
    yield "alpha"
    yield "beta"
    yield "gamma"

@node(stream_in=["chunk"])
async def Consumer1(chunk: Stream[str]):
    """Consumes with variable delays - EXACTLY 3 manual __anext__() calls."""
    print(">>> Consumer1: ENTERED FUNCTION BODY <<<")
    c_iter = chunk.__aiter__()

    # First chunk: immediate
    c1 = await c_iter.__anext__()
    consumer1_chunks.append(c1)
    print(f"Consumer1 got: {c1}")

    # Second chunk: small delay
    await sleep(0.01)
    c2 = await c_iter.__anext__()
    consumer1_chunks.append(c2)
    print(f"Consumer1 got: {c2}")

    # Third chunk: no delay
    c3 = await c_iter.__anext__()
    consumer1_chunks.append(c3)
    print(f"Consumer1 got: {c3}")

    print("Consumer1: Returning WITHOUT checking if stream is done")
    print(">>> Consumer1: REACHED END OF FUNCTION BODY <<<")
    # Note: NOT calling __anext__() again to check for StopAsyncIteration!

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    """Consumes with consistent delay - uses async for."""
    print(">>> Consumer2: ENTERED FUNCTION BODY <<<")
    print("Consumer2: Starting async for")
    async for c in chunk:
        await sleep(0.03)
        consumer2_chunks.append(c)
        print(f"Consumer2 got: {c}")
    print("Consumer2: Exited async for")
    print(">>> Consumer2: REACHED END OF FUNCTION BODY <<<")

with FlowHDL() as f:
    f.source = ThreeChunkSource()
    f.c1 = Consumer1(f.source)
    f.c2 = Consumer2(f.source)

print("Starting flow...")
import signal
signal.alarm(3)
try:
    f.run_until_complete()
    print("Flow completed!")
except Exception as e:
    print(f"Flow ended with: {type(e).__name__}: {e}")

print(f"consumer1_chunks: {consumer1_chunks}")
print(f"consumer2_chunks: {consumer2_chunks}")
