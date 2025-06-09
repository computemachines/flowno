from flowno import AsyncQueue, sleep
from flowno.core.event_loop.event_loop import EventLoop
import time
import threading

def test_put_item_from_outside():
    """
    Test that we can put an item into a queue from outside the event loop.

    I'm not going to use threads, I'm just going to call non-async code
    inside the event loop.
    """
    loop = EventLoop()

    async def put_item(q: AsyncQueue[str]):
        await q.put("hello")

    async def queue_test():
        q = AsyncQueue[str]()

        loop.create_task(put_item(q))


        assert await q.get() == "hello"

    loop.run_until_complete(queue_test(), join=True)

def assert_fuzzy_log(log, expected_log):
    """
    Assert that the log matches the expected log, allowing for some fuzziness
    in the timing.
    """
    assert len(log) == len(expected_log), f"Log length mismatch: {len(log)} != {len(expected_log)}"
    for i, (expected_time, expected_msg) in enumerate(expected_log):
        actual_time, actual_msg = log[i]
        assert actual_msg == expected_msg
        assert abs(actual_time - expected_time) < 0.05, f"Time mismatch for {expected_msg}: {actual_time} != {expected_time} (index {i})"

def test_create_task_runs1():
    """
    Test that we can create a task and run it with correct timing.
    """
    loop = EventLoop()

    log = []
    start_time = time.time()
    def append_to_log(msg):
        log.append((time.time() - start_time, msg))

    async def task():
        append_to_log("TASK EXECUTING")
    
    def create_task_thread():
        time.sleep(0.1)
        append_to_log("TASK CREATING")
        loop.create_task(task())
        append_to_log("TASK CREATED")
        
    async def main():
        append_to_log("MAIN START")
        await sleep(1)
        append_to_log("MAIN END")

    threading.Thread(target=create_task_thread).start()
    loop.run_until_complete(main(), join=True)

    expected_orders = [
        [
            "MAIN START",
            "TASK CREATING",
            "TASK CREATED",
            "TASK EXECUTING",
            "MAIN END",
        ],
        [
            "MAIN START",
            "TASK CREATING",
            "TASK EXECUTING",
            "TASK CREATED",
            "MAIN END",
        ],
    ]

    msgs = [msg for _, msg in log]
    assert msgs in expected_orders



def test_create_task_runs2():
    """
    Test that create_task wakes up the event loop blocked on `await queue.get()`
    
    FAILURE CASE: Event loop doesn't wake up when task is created from external thread.
    The loop gets stuck in a blocking poll() call, never executing the task.
    Log only shows "MAIN START", "TASK CREATING", "TASK CREATED" before timeout.
    Need to implement a mechanism to notify the event loop when tasks are added from
    other threads.
    """
    loop = EventLoop()
    q = AsyncQueue[str]()

    log = []
    start_time = time.time()
    def append_to_log(msg):
        print(msg)
        log.append((time.time() - start_time, msg))

    async def task(q: AsyncQueue[str]):
        await sleep(0.05)
        append_to_log("TASK EXECUTING")
        await q.put("hello")
        append_to_log("TASK FINISHED")
    
    def create_task_thread():
        time.sleep(0.1)
        append_to_log("TASK CREATING")
        loop.create_task(task(q))
        append_to_log("TASK CREATED")
        
    async def main():
        append_to_log("MAIN START")
        value = await q.get()
        append_to_log(f"MAIN GOT VALUE {value}")
        append_to_log("MAIN END")

    threading.Thread(target=create_task_thread).start()
    loop.run_until_complete(main(), join=True)

    expected_orders = [
        [
            "MAIN START",
            "TASK CREATING",
            "TASK CREATED",
            "TASK EXECUTING",
            "MAIN GOT VALUE hello",
            "MAIN END",
            "TASK FINISHED",
        ],
        [
            "MAIN START",
            "TASK CREATING",
            "TASK EXECUTING",
            "TASK CREATED",
            "MAIN GOT VALUE hello",
            "MAIN END",
            "TASK FINISHED",
        ],
        [
            "MAIN START",
            "TASK CREATING",
            "TASK EXECUTING",
            "MAIN GOT VALUE hello",
            "MAIN END",
            "TASK FINISHED",
            "TASK CREATED",
        ],
    ]

    msgs = [msg for _, msg in log]
    assert msgs in expected_orders

