"""
Exploratory type-checking of the FlowHDL context and node decorator.
The goal is to verify that node factories produce correctly typed DraftNodes
while inside the FlowHDL context.
"""

from typing_extensions import assert_type

from flowno import node, FlowHDL, DraftNode

@node
async def Add(x: int, y: int) -> int:
    return x + y

@node
async def Const() -> int:
    return 1

with FlowHDL() as f:
    first = Const()
    second = Const()
    f.sum = Add(first, second)
    _ = assert_type(first, DraftNode)
    _ = assert_type(f.sum, DraftNode)
