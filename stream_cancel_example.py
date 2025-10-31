from flowno import FlowHDL, node, Stream
from flowno.core.flow.instrumentation import PrintInstrument as FlowLogInstrument
from flowno.core.event_loop.instrumentation import PrintInstrument as EventLoopLogInstrument

# @node
# async def Source():
#     for i in range(20):
#         yield i

# @node(stream_in=["numbers"])
# async def Stringify(numbers: Stream[int]):
#     async for number in numbers:
#         if number == 10:
#             await numbers.cancel()
#         yield str(number)

# @node
# async def Print(concatenated: str):
#     print(concatenated)

## Even simpler example to demonstrate cancellation
@node
async def Source():
    print("Source: Yielding 1")
    try:
        yield 1
    except Exception as e:
        print(f"Source: Caught exception {e}")
    print("Source: Yielding 2")
    try:
        yield 2
    except Exception as e:
        print(f"Source: Caught exception {e}")
    print("Source: Yielding 3")
    try:
        yield 3
    except Exception as e:
        print(f"Source: Caught exception {e}")
    
    print("Source: Returning")
    return

@node(stream_in=["numbers"])
async def CancelAfterFirst(numbers: Stream[int]):
    it = numbers.__aiter__()
    print("CancelAfterFirst: Awaiting first number")
    try:
        first = await it.__anext__()
        print(f"CancelAfterFirst: Received first number: {first}")
    except Exception as e:
        print(f"CancelAfterFirst: Caught exception {e}")

    print("CancelAfterFirst: Cancelling stream")
    await numbers.cancel()

    print("CancelAfterFirst: Awaiting second number")
    try:
        second = await it.__anext__()
        print(f"CancelAfterFirst: Received second number: {second}")
    except Exception as e:
        print(f"CancelAfterFirst: Caught exception {repr(e)}")

    print("CancelAfterFirst: Awaiting third number")
    try:
        third = await it.__anext__()
        print(f"CancelAfterFirst: Received third number: {third}")
    except Exception as e:
        print(f"CancelAfterFirst: Caught exception {e!r}")

    print("CancelAfterFirst: Returning")
    return

@node
async def Collect(numbers: list[int]):
    """This node consumes at run-level-0 to force a full run."""
    print(f"Collect: Collected numbers: {numbers!r}")

with FlowHDL() as f:
    f.source = Source()
    CancelAfterFirst(f.source)
    Collect(f.source)


with FlowLogInstrument():
    with EventLoopLogInstrument():
        f.run_until_complete(_debug_max_wait_time=5)