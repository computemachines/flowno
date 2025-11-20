"""Test to see the exact timing of Consumer1 restart vs Consumer2 exit."""

from flowno import FlowHDL, Stream, node
from flowno.core.event_loop.primitives import sleep

@node
async def ThreeChunkSource():
    yield "alpha"
    yield "beta"
    yield "gamma"

@node(stream_in=["chunk"])
async def Consumer1(chunk: Stream[str]):
    print("=== Consumer1: Starting iteration ===")
    chunks = []
    async for c in chunk:
        print(f"Consumer1: got {c}")
        chunks.append(c)
    print(f"=== Consumer1: Exited async for, about to return ===")
    return chunks

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    print("=== Consumer2: Starting iteration ===")
    chunks = []
    async for c in chunk:
        print(f"Consumer2: got {c}")
        await sleep(0.01)  # Small delay
        chunks.append(c)
    print(f"=== Consumer2: Exited async for, about to return ===")
    return chunks

with FlowHDL() as f:
    f.source = ThreeChunkSource()
    f.c1 = Consumer1(f.source)
    f.c2 = Consumer2(f.source)

print("Starting flow...")
try:
    import signal
    signal.alarm(3)  # 3 second timeout
    f.run_until_complete()
except Exception as e:
    print(f"Flow ended with: {e}")

print(f"Consumer1 gen: {f.c1.generation}, data: {f.c1.get_data()}")
print(f"Consumer2 gen: {f.c2.generation}, data: {f.c2.get_data()}")
