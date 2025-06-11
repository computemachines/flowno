"""
Exploratory type-checking for AsyncQueue.
This test checks that queue methods return values with the expected generic type.
"""

from typing_extensions import assert_type

from flowno import AsyncQueue

q_int: AsyncQueue[int] = AsyncQueue()

async def use_queue() -> int:
    await q_int.put(1)
    item1 = await q_int.get()
    _ = assert_type(item1, int)

    await q_int.put(2)
    peeked = await q_int.peek()
    _ = assert_type(peeked, int)

    await q_int.close()
    return item1
