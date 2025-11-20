"""Test to see which nodes get enqueued when producer finishes."""

from flowno import FlowHDL, Stream, node

@node
async def ThreeChunkSource():
    yield "alpha"
    yield "beta"
    yield "gamma"

@node(stream_in=["chunk"])
async def Consumer1(chunk: Stream[str]):
    chunks = []
    async for c in chunk:
        chunks.append(c)
    print(f"Consumer1 done")
    return chunks

@node(stream_in=["chunk"])
async def Consumer2(chunk: Stream[str]):
    chunks = []
    async for c in chunk:
        chunks.append(c)
    print(f"Consumer2 done")
    return chunks

with FlowHDL() as f:
    f.source = ThreeChunkSource()
    f.c1 = Consumer1(f.source)
    f.c2 = Consumer2(f.source)

# Check what consumers are connected at what run levels
source = f.source
print(f"All output nodes: {source.get_output_nodes()}")
print(f"Run-level-0 input ports: {source.get_output_nodes_by_run_level(0)}")
print(f"Run-level-1 input ports: {source.get_output_nodes_by_run_level(1)}")

# Don't actually run to avoid hang
# f.run_until_complete()
