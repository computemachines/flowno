from flowno import node, FlowHDL, FlowHDLView, DraftNode


@node
async def Add(a: int, b: int) -> int:
    """Adds two integers."""
    return a + b


# Add is now a DraftNode class factory
# Add: Callable[[NodeOutput[int] | int, NodeOutput[int] | int], DraftNode[int, int, (int,)]]


@node
async def Multiply(a: int, b: int) -> int:
    """Multiplies two integers."""
    return a * b


# Multiply is now a DraftNode class factory
# Multiply: Callable[[NodeOutput[int] | int, NodeOutput[int] | int], DraftNode[int, int, (int,)]]


@node.template
def TripleProduct(f: FlowHDLView, a: int, b: int, c: int) -> DraftNode[int]:
    """Returns a node and composes other nodes."""
    f.left = Multiply(a, b)
    f.middle = Multiply(b, c)
    f.right = Multiply(c, a)
    f.result_temp = Add(f.left, f.middle)
    f.result = Add(f.result_temp, f.right)
    return f.result


# TripleProduct is now a DraftGroupNode class factory
# The dynamically generated DraftGroupNode subclass __init__ method needs to invoke the wrapped function using a FlowHDLView instance prepending the arguments.
# TripleProduct: Callable[[NodeOutput[int] | int, NodeOutput[int] | int, NodeOutput[int] | int], DraftGroupNode[int, int, int, (int,)]]


def static_group_example():
    with FlowHDL() as f:
        f.result = TripleProduct(2, 3, 4)

    f.run_until_complete()
    print(f.result.output())  # Should print 26, which is (2*3) + (3*4) + (4*2)


@node
def Input() -> int:
    """Get user input."""
    return int(input("Enter an integer: "))


# Input is now a DraftNode class factory
# Input: Callable[[], DraftNode[(int,)]]


# This is not a group node, it is a regular node that returns a DraftGroupNode instead of an int
@node
def GenerateFlowAtEvaluation(a: int) -> DraftGroupNode[int, (int,)]:
    """Takes a normal arument and generates a flow at evaluation time."""
    print(f"Generating flow at evaluation with input: {a}")

    # TODO: Think through some way to generate a DraftGroupNode from a string source code

    return TripleProduct(a, a, a)


# GenerateFlowAtEvaluation is now a DraftNode class factory
# GenerateFlowAtEvaluation: Callable[[NodeOutput[int] | int], (DraftGroupNode[int, (int,)],)]


def dynamic_group_example():
    with FlowHDL() as f:
        f.a = Input()
        f.generate_dynamic_flow = GenerateFlowAtEvaluation(f.a)
        f.dyn = DynamicGroup[int, (int,)](f.a, hdl=f.generate_dynamic_flow)

    f.run_until_complete()
    print(f.dyn.output())
