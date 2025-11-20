"""Test: Consumer1 properly checks for stream completion."""

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
    """Consumes with variable delays - checks for completion with extra __anext__()."""
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

    # PROPERLY check if stream is done
    print("Consumer1: Checking if stream is done...")
    try:
        c4 = await c_iter.__anext__()
        print(f"Consumer1 got unexpected: {c4}")
        consumer1_chunks.append(c4)
    except StopAsyncIteration:
        print("Consumer1: Stream is done (got StopAsyncIteration)")

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    """Consumes with consistent delay - uses async for."""
    print("Consumer2: Starting async for")
    async for c in chunk:
        await sleep(0.03)
        consumer2_chunks.append(c)
        print(f"Consumer2 got: {c}")
    print("Consumer2: Exited async for")

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
