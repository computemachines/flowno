"""Simple test to verify single consumer behavior."""

from flowno import FlowHDL, Stream, node

@node
async def ThreeChunkSource():
    """Yield three distinct chunks."""
    print("Source: yielding alpha")
    yield "alpha"
    print("Source: yielding beta")
    yield "beta"
    print("Source: yielding gamma")
    yield "gamma"
    print("Source: done")

@node(stream_in=["chunk"])
async def SingleConsumer(chunk: Stream[str]):
    """Consume all chunks."""
    print("Consumer: starting")
    chunks = []
    async for c in chunk:
        print(f"Consumer: got {c}")
        chunks.append(c)
    print(f"Consumer: done, got {chunks}")
    return chunks

with FlowHDL() as f:
    f.source = ThreeChunkSource()
    f.consumer = SingleConsumer(f.source)

print("Starting flow...")
f.run_until_complete()
print("Flow complete!")

consumer = f.consumer
print(f"Consumer generation: {consumer.generation}")
print(f"Consumer data: {consumer.get_data()}")

source = f.source
print(f"Source generation: {source.generation}")
print(f"Source run-level-0 data: {source.get_data(0)}")
