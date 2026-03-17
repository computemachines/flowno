"""Trace every send/throw cycle in the event loop for simple.py"""
from flowno.core.event_loop import EventLoop
from flowno.core.event_loop.instrumentation import (
    EventLoopInstrument, TaskSendMetadata, TaskThrowMetadata,
)
from flowno.core.event_loop.primitives import sleep

step = 0

class TraceInstrument(EventLoopInstrument):
    def on_task_before_send(self, metadata: TaskSendMetadata):
        global step
        step += 1
        print(f"[{step:3d}] SEND  task={metadata.task!r}")
        print(f"       value={metadata.send_value!r}")

    def on_task_after_send(self, metadata: TaskSendMetadata, command):
        print(f"       → {type(command).__name__}")
        print()

    def on_task_before_throw(self, metadata: TaskThrowMetadata):
        global step
        step += 1
        print(f"[{step:3d}] THROW task={metadata.task!r}")
        print(f"       exception={metadata.exception!r}")

    def on_task_after_throw(self, metadata: TaskThrowMetadata, command):
        print(f"       → {type(command).__name__}")
        print()

    def on_task_completed(self, task, return_value):
        global step
        step += 1
        print(f"[{step:3d}] DONE  task={task!r}")
        print(f"       returned={return_value!r}")
        print()

    def on_task_error(self, task, exception):
        global step
        step += 1
        print(f"[{step:3d}] ERROR task={task!r}")
        print(f"       exception={exception!r}")
        print()


async def my_sleeper(message: str):
    print("starting sleeper")
    _ = await sleep(1)
    print("done sleeping")
    print(f"message: {message}")

async def main():
    await my_sleeper("hello")

el = EventLoop()
with TraceInstrument():
    el.run_until_complete(main())
