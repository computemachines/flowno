"""
Exploratory type-checking tests for EventLoop.run_until_complete.
Verifies return types when join=True and join=False.
"""

from typing_extensions import assert_type

from flowno import EventLoop, sleep

async def root_task() -> int:
    result: float = await sleep(0)
    _ = assert_type(result, float)
    return 42


def explore_join_behavior() -> None:
    loop: EventLoop = EventLoop()

    join_result: int = loop.run_until_complete(root_task(), join=True)
    _ = assert_type(join_result, int)

    no_join_result: None = loop.run_until_complete(root_task(), join=False)
    _ = assert_type(no_join_result, None)

