from flowno import node, FlowHDL
from flowno.core.flow_hdl_view import FlowHDLView


@node
async def MyConstant() -> int:
    """Returns a constant value."""
    return 42


@node
async def Increment(a: int) -> int:
    """Increments the input integer by 1."""
    return a + 1


@node.template
def MyGroup(f: FlowHDLView, g_input: int):
    """A simple group that increments an input value by 2."""
    f.incremented_twice = Increment(Increment(g_input))
    return f.incremented_twice


@node
async def Print(value: int, prefix: str = "Value: ") -> None:
    """Prints the value with a prefix."""
    print(f"{prefix}{value}")


if __name__ == "__main__":
    with FlowHDL() as f:
        f.my_constant = MyConstant()
        f.result = MyGroup(f.my_constant)
        f.print_result = Print(f.result)
    f.run_until_complete()

    # No run_until_complete; just ensure group finalization messages appear
