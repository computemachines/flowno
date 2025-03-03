#!/usr/bin/env python
"""
Example: Cycle without default error

This example demonstrates a cyclic dependency that lacks a default value,
which will raise a MissingDefaultError.
"""
from flowno import FlowHDL, node


@node
async def A(x: int):
    return x + 1


@node
async def B(x: str, y: int):
    """
    This node does not specify a default for y.
    In a cycle, at least one node must provide a default.
    """
    print(f"x: {x}")
    return y + 2


def main():
    with FlowHDL() as f:
        # Create a cycle where B depends on A cyclically through argument 'y'.
        f.a = A(f.b)
        f.b = B("hello", f.a)

    # Expect a MissingDefaultError due to the cycle without defaults.
    f.run_until_complete(stop_at_node_generation=(1,))
    # The MissingDefaultError will list the options for solving the error.


# flowno.core.node_base.MissingDefaultError: Detected a cycle without default values. You must add defaults to the indicated arguments for at least ONE of the following nodes:
#   A#0 must have defaults for EACH/ALL the underlined parameters:
#   Defined at /home/tparker/projects/flowno/examples/cycle_no_default_error.py:4
#   Full Signature:
#   A(x: int)
#     ------
# OR
#   B#0 must have defaults for EACH/ALL the underlined parameters:
#   Defined at /home/tparker/projects/flowno/examples/cycle_no_default_error.py:9
#   Full Signature:
#   B(x: str, y: int)
#             ------

if __name__ == "__main__":
    main()
