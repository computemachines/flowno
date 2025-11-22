"""Debug script to trace streaming concurrency issue."""
import logging
from flowno import node, FlowHDL, Stream
from flowno.core.event_loop.primitives import sleep

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s:%(lineno)d - %(message)s',
    datefmt='%H:%M:%S'
)

consumer1_chunks = []
consumer2_chunks = []

@node
async def TwoChunkSource():
    """Yield two distinct chunks."""
    print(">>> SOURCE: yielding 'alpha'")
    yield "alpha"
    print(">>> SOURCE: yielding 'beta'")
    yield "beta"
    print(">>> SOURCE: done")

@node(stream_in=["chunk"])
async def Consumer1(chunk: Stream[str]):
    """Consumes with a small delay."""
    print(">>> CONSUMER1: starting")
    c_iter = chunk.__aiter__()

    # First chunk: immediate
    print(">>> CONSUMER1: requesting first chunk")
    c1 = await c_iter.__anext__()
    print(f">>> CONSUMER1: got first chunk: {c1!r}")
    consumer1_chunks.append(c1)

    # Small delay before second chunk
    print(">>> CONSUMER1: sleeping 0.01s")
    await sleep(0.01)

    # Second chunk
    print(">>> CONSUMER1: requesting second chunk")
    c2 = await c_iter.__anext__()
    print(f">>> CONSUMER1: got second chunk: {c2!r}")
    consumer1_chunks.append(c2)
    print(">>> CONSUMER1: done")

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    """Consumes with consistent delay."""
    print(">>> CONSUMER2: starting")
    async for c in chunk:
        print(f">>> CONSUMER2: got chunk: {c!r}, sleeping 0.03s")
        await sleep(0.03)
        consumer2_chunks.append(c)
    print(">>> CONSUMER2: done")

print("=" * 80)
print("STARTING TEST")
print("=" * 80)

with FlowHDL() as f:
    f.source = TwoChunkSource()
    f.c1 = Consumer1(f.source)
    f.c2 = Consumer2(f.source)

f.run_until_complete()

print("=" * 80)
print("TEST COMPLETE")
print(f"Consumer1 chunks: {consumer1_chunks}")
print(f"Consumer2 chunks: {consumer2_chunks}")
print("=" * 80)

assert consumer1_chunks == ["alpha", "beta"], f"Consumer1 got {consumer1_chunks}"
assert consumer2_chunks == ["alpha", "beta"], f"Consumer2 got {consumer2_chunks}"
print("SUCCESS!")
