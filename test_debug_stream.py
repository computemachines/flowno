"""Debug test for stream hanging issue."""
import logging
from flowno import FlowHDL, Stream, node
from flowno.core.event_loop.primitives import sleep

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

consumer1_chunks = []
consumer2_chunks = []

@node
async def ThreeChunkSource():
    """Yield three distinct chunks."""
    print("SOURCE: Yielding alpha")
    yield "alpha"
    print("SOURCE: Yielding beta")
    yield "beta"
    print("SOURCE: Yielding gamma")
    yield "gamma"
    print("SOURCE: Done yielding")

@node(stream_in=["chunk"])
async def Consumer1(chunk: Stream[str]):
    """Consumes with variable delays."""
    print("CONSUMER1: Starting")
    c_iter = chunk.__aiter__()

    # First chunk: immediate
    print("CONSUMER1: Getting first chunk")
    c1 = await c_iter.__anext__()
    print(f"CONSUMER1: Got first chunk: {c1}")
    consumer1_chunks.append(c1)

    # Second chunk: small delay
    print("CONSUMER1: Sleeping before second chunk")
    await sleep(0.01)
    print("CONSUMER1: Getting second chunk")
    c2 = await c_iter.__anext__()
    print(f"CONSUMER1: Got second chunk: {c2}")
    consumer1_chunks.append(c2)

    # Third chunk: no delay
    print("CONSUMER1: Getting third chunk")
    c3 = await c_iter.__anext__()
    print(f"CONSUMER1: Got third chunk: {c3}")
    consumer1_chunks.append(c3)
    print("CONSUMER1: Done")

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    """Consumes with consistent delay."""
    print("CONSUMER2: Starting")
    async for c in chunk:
        print(f"CONSUMER2: Got chunk: {c}")
        await sleep(0.03)
        print(f"CONSUMER2: Appending chunk: {c}")
        consumer2_chunks.append(c)
    print("CONSUMER2: Done")

if __name__ == "__main__":
    with FlowHDL() as f:
        f.source = ThreeChunkSource()
        f.c1 = Consumer1(f.source)
        f.c2 = Consumer2(f.source)

    print("MAIN: Running flow")
    f.run_until_complete(_debug_max_wait_time=5)
    print("MAIN: Flow complete")

    print(f"Consumer1 chunks: {consumer1_chunks}")
    print(f"Consumer2 chunks: {consumer2_chunks}")
