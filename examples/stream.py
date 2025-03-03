#!/usr/bin/env python
"""
Stream Processing Example

This example demonstrates nodes that produce and consume streaming data.
"""

from collections.abc import AsyncGenerator

from flowno import FlowHDL, node
from flowno.core.flow.flow import TerminateLimitReached
from flowno.core.node_base import Stream


@node
async def Words(input: list[str] | None = None) -> AsyncGenerator[str, None]:
    """
    Yields words from a provided list; defaults to ["hello", "world"].
    """
    if not input:
        input = ["hello", "world"]
    for word in input:
        yield word
    raise StopAsyncIteration("done")


@node(stream_in=["words"])
async def Upcase(words: Stream[str]) -> AsyncGenerator[str, None]:
    """
    Converts each word to uppercase.
    """
    print("Upcase node started")
    async for word in words:
        print(f"Upcasing: {word}")
        yield word.upper()


@node(stream_in=["words"])
async def ReverseSentence(words: Stream[str]) -> str:
    """
    Builds a reversed sentence from the streamed words.
    """
    accumulator = ""
    async for word in words:
        accumulator = word + " " + accumulator
    return accumulator.strip()


@node
async def SentenceToList(sentence: str) -> list[str]:
    return sentence.split()


def main():
    with FlowHDL() as f:
        f.words = Words(f.split)
        f.upcase = Upcase(f.words)
        f.reverse = ReverseSentence(f.upcase)
        f.split = SentenceToList(f.reverse)

    try:
        f.run_until_complete(stop_at_node_generation=(3,))
    except TerminateLimitReached:
        pass

    # Retrieve and verify the final result.
    result = f.reverse.get_data(0)
    print("Final reversed sentence:", result)
    assert result == ("WORLD HELLO",)


if __name__ == "__main__":
    main()
