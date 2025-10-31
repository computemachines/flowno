"""Stream Cancellation Example

Usage:
  stream_cancel_example.py [--verbose]
  stream_cancel_example.py (-h | --help)

Options:
  -h --help     Show this screen.
  --verbose     Enable verbose logging with flow and event loop instrumentation.
"""
from docopt import docopt
from flowno import FlowHDL, node, Stream
from flowno.core.node_base import StreamCancelled
from flowno.core.flow.instrumentation import PrintInstrument as FlowLogInstrument
from flowno.core.event_loop.instrumentation import PrintInstrument as EventLoopLogInstrument

## Even simpler example to demonstrate cancellation
@node
async def Source():
    print("Source: Yielding 1")
    try:
        yield "one"
    except StreamCancelled as e:
        print("Source: Caught StreamCancelled")
    except Exception as e:
        print(f"Source: Caught exception {e}")
    finally:
        print("Source: Finally block executed after first yield")
    print("Source: Returning")

@node(stream_in=["numbers"])
async def CancelAfterFirst(numbers: Stream[str]):
    it = numbers.__aiter__()
    first = await it.__anext__()

    await numbers.cancel()

    print("CancelAfterFirst: Awaiting second number")
    try:
        second = await it.__anext__()
        print(f"CancelAfterFirst: ERROR!! Received a second number: {second}?!?")
    except StopAsyncIteration as e:
        print("CancelAfterFirst: Caught StopAsyncIteration as expected after cancellation")
    except Exception as e:
        print(f"CancelAfterFirst: ERROR Caught exception {e!r}")

    print("CancelAfterFirst: Returning")
    return

@node
async def Collect(numbers: list[str]):
    """This node consumes at run-level-0 to force a full run."""
    print(f"Collect: Collected numbers: {numbers!r}")

if __name__ == "__main__":
    args = docopt(__doc__)
    
    with FlowHDL() as f:
        f.source = Source()
        CancelAfterFirst(f.source)
        Collect(f.source)

    if args['--verbose']:
        with FlowLogInstrument():
            with EventLoopLogInstrument():
                f.run_until_complete(_debug_max_wait_time=5)
    else:
        f.run_until_complete(_debug_max_wait_time=5)