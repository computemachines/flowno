"""
This is a typechecking test. Every variable must have a type annotation.
Runtime assertions are never evaluated. `assert_type` is used instead.
"""


from collections.abc import Awaitable
from typing_extensions import assert_type
from flowno import spawn, sleep, EventLoop
from flowno.core.event_loop.tasks import TaskHandle

# Testing return value inference
async def worker_task1():
    actual: float = await sleep(0.1)
    return actual

async def worker_task2() -> str:
    return "Hello, World!"


async def main_task():
    worker_taskhandle = await spawn(worker_task1())
    _worker1_result: float = await worker_taskhandle.join()


    co_worker = spawn(worker_task2())
    _ = assert_type(co_worker, Awaitable[TaskHandle[str]])

    co_worker_result: TaskHandle[str] = await co_worker

    return await co_worker_result.join()


loop = EventLoop()

_result: str = loop.run_until_complete(main_task(), join=True)