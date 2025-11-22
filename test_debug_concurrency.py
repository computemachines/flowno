#!/usr/bin/env python
"""Minimal test to debug the concurrency timeout issue."""

import logging
from flowno import FlowHDL, node, Stream, sleep

logging.basicConfig(level=logging.DEBUG)

consumer1_chunks = []
consumer2_chunks = []

@node
async def ThreeChunkSource():
    """Yield three distinct chunks."""
    print("SOURCE: yielding alpha")
    yield "alpha"
    print("SOURCE: yielding beta")
    yield "beta"
    print("SOURCE: yielding gamma")
    yield "gamma"
    print("SOURCE: done yielding")

@node(stream_in=["chunk"])
async def Consumer1(chunk: Stream[str]):
    """Consumes with variable delays."""
    c_iter = chunk.__aiter__()

    # First chunk: immediate
    c1 = await c_iter.__anext__()
    print(f"CONSUMER1: got {c1}")
    consumer1_chunks.append(c1)

    # Second chunk: small delay
    await sleep(0.01)
    c2 = await c_iter.__anext__()
    print(f"CONSUMER1: got {c2}")
    consumer1_chunks.append(c2)

    # Third chunk: no delay
    c3 = await c_iter.__anext__()
    print(f"CONSUMER1: got {c3}")
    consumer1_chunks.append(c3)
    print("CONSUMER1: done consuming")

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    """Consumes with consistent delay."""
    async for c in chunk:
        print(f"CONSUMER2: sleeping before consuming {c}")
        await sleep(0.03)
        print(f"CONSUMER2: got {c}")
        consumer2_chunks.append(c)
    print("CONSUMER2: done consuming")

with FlowHDL() as f:
    f.source = ThreeChunkSource()
    f.c1 = Consumer1(f.source)
    f.c2 = Consumer2(f.source)

print("Starting flow...")
f.run_until_complete()
print("Flow complete!")

print(f"consumer1_chunks: {consumer1_chunks}")
print(f"consumer2_chunks: {consumer2_chunks}")

assert consumer1_chunks == ["alpha", "beta", "gamma"], "Consumer1 should receive all chunks in order"
assert consumer2_chunks == ["alpha", "beta", "gamma"], "Consumer2 should receive all chunks in order"
