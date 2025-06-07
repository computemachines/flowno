from flowno import node, FlowHDL, DraftNode

@node
async def MyConstant() -> int:
    """Returns a constant value."""
    return 42

@node
async def Increment(a: int) -> int:
    """Increments the input integer by 1."""
    return a + 1

@node.template
def MyGroup(f: FlowHDL, g_input: int):
    """A simple group that increments a constant value by 2."""
    f.incremented_twice = Increment(Increment(f.constant))
    return f.incremented_twice

@node
async def Print(value: int, prefix: str = "Value: ") -> None:
    """Prints the value with a prefix."""
    print(f"{prefix}{value}")

if __name__ == "__main__":
    with FlowHDL() as f:
        f.constant = MyConstant()
        f.result = MyGroup(f.constant)
        f.print_result = Print(f.result)

    f.run_until_complete()
    # Should print "Final Result: Value: 44"