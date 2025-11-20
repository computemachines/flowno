"""Test: Both consumers don't check for stream completion."""

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
    """Manually calls __anext__() exactly 3 times WITHOUT checking completion."""
    c_iter = chunk.__aiter__()

    c1 = await c_iter.__anext__()
    consumer1_chunks.append(c1)
    print(f"Consumer1 got: {c1}")

    await sleep(0.01)
    c2 = await c_iter.__anext__()
    consumer1_chunks.append(c2)
    print(f"Consumer1 got: {c2}")

    c3 = await c_iter.__anext__()
    consumer1_chunks.append(c3)
    print(f"Consumer1 got: {c3}")

    print("Consumer1: Returning WITHOUT checking if stream is done")

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    """Also manually calls __anext__() exactly 3 times WITHOUT checking completion."""
    c_iter = chunk.__aiter__()

    c1 = await c_iter.__anext__()
    consumer2_chunks.append(c1)
    print(f"Consumer2 got: {c1}")

    await sleep(0.03)
    c2 = await c_iter.__anext__()
    consumer2_chunks.append(c2)
    print(f"Consumer2 got: {c2}")

    await sleep(0.03)
    c3 = await c_iter.__anext__()
    consumer2_chunks.append(c3)
    print(f"Consumer2 got: {c3}")

    print("Consumer2: Returning WITHOUT checking if stream is done")

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
