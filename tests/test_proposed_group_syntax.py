import pytest

def test_triple_product_group_node():
    from flowno import node, FlowHDL, FlowHDLView, DraftNode

    @node
    async def Add(a: int, b: int) -> int:
        return a + b

    @node
    async def Multiply(a: int, b: int) -> int:
        return a * b

    @node.template
    def TripleProduct(f: FlowHDLView, a: int, b: int, c: int) -> DraftNode[int]:
        f.left = Multiply(a, b)
        f.middle = Multiply(b, c)
        f.right = Multiply(c, a)
        f.result_temp = Add(f.left, f.middle)
        f.result = Add(f.result_temp, f.right)
        return f.result

    with FlowHDL() as f:
        f.result = TripleProduct(2, 3, 4)

    f.run_until_complete()
    assert f.result.get_data() == (26,)


def test_increment_group_node():
    """Illustrate a nested group that increments an input twice."""
    from flowno import node, FlowHDL, FlowHDLView, DraftNode

    @node
    async def A() -> int:
        return 42

    @node
    async def Inc(x: int) -> int:
        return x + 1

    @node.template
    def MyGroup(f: FlowHDLView, g_in: int) -> DraftNode[int]:
        f.incremented_twice = Inc(Inc(g_in))
        return f.incremented_twice

    @node
    async def Print(x: int):
        print(x)

    with FlowHDL() as f:
        f.a = A()
        f.b = MyGroup(f.a)
        f.c = Print(f.b)

    f.run_until_complete()
    assert f.b.get_data() == (44,)
