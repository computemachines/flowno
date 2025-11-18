#!/usr/bin/env python3
"""Demonstration of conditional execution using PropagateIf and the .if_() method.

This example shows how to conditionally execute nodes in a dataflow graph using:
1. PropagateIf node directly
2. The convenient .if_() method
"""

from flowno import FlowHDL, node, PropagateIf


@node
async def BooleanSource(value: bool) -> bool:
    """Return a constant boolean value."""
    return value


@node
async def IntSource(value: int) -> int:
    """Return a constant integer value."""
    return value


@node
async def Add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@node
async def Multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@node
async def Print(label: str, value: int) -> int:
    """Print a labeled value."""
    print(f"{label}: {value}")
    return value


def example_1_basic_propagate_if():
    """Example 1: Basic PropagateIf usage."""
    print("\n=== Example 1: Basic PropagateIf ===")

    with FlowHDL() as f:
        f.enabled = BooleanSource(True)
        f.value = IntSource(42)
        f.gated = PropagateIf(f.enabled, f.value)
        f.result = Print("Result", f.gated)

    f.run_until_complete()
    print(f"Output: {f.result.get_data()}")


def example_2_if_method():
    """Example 2: Using the convenient .if_() method."""
    print("\n=== Example 2: Using .if_() method ===")

    with FlowHDL() as f:
        f.enabled = BooleanSource(True)
        f.value = IntSource(42)
        # Same as PropagateIf(f.enabled, f.value) but more fluent
        f.result = Print("Result", f.value.if_(f.enabled))

    f.run_until_complete()
    print(f"Output: {f.result.get_data()}")


def example_3_skip_propagation():
    """Example 3: Skip propagation when condition is False."""
    print("\n=== Example 3: Skip propagation (condition=False) ===")

    with FlowHDL() as f:
        f.enabled = BooleanSource(False)
        f.value = IntSource(42)
        f.gated = f.value.if_(f.enabled)
        f.doubled = Multiply(f.gated, 2)
        f.result = Print("Result", f.doubled)

    f.run_until_complete()

    print(f"Gated is skipped: {f.gated.is_skipped((0,))}")
    print(f"Doubled is skipped: {f.doubled.is_skipped((0,))}")
    print(f"Result is skipped: {f.result.is_skipped((0,))}")
    print("Notice: Print was never called because the entire chain was skipped!")


def example_4_chaining():
    """Example 4: Chaining operations with .if_()."""
    print("\n=== Example 4: Chaining with .if_() ===")

    with FlowHDL() as f:
        f.enabled = BooleanSource(True)
        f.value = IntSource(10)
        # Chain operations: value → if_(enabled) → add 5 → multiply by 2
        f.result = Print(
            "Result",
            Multiply(Add(f.value.if_(f.enabled), 5), 2)
        )

    f.run_until_complete()
    # ((10 if True) + 5) * 2 = (10 + 5) * 2 = 15 * 2 = 30
    print(f"Output: {f.result.get_data()}")


def example_5_multiple_conditions():
    """Example 5: Multiple conditions (AND logic)."""
    print("\n=== Example 5: Multiple conditions (AND logic) ===")

    with FlowHDL() as f:
        f.cond1 = BooleanSource(True)
        f.cond2 = BooleanSource(True)
        f.value = IntSource(100)

        # Both conditions must be True
        f.result = Print(
            "Result",
            f.value.if_(f.cond1).if_(f.cond2)
        )

    f.run_until_complete()
    print(f"Output: {f.result.get_data()}")

    # Try with one condition False
    print("\nWith cond2=False:")
    with FlowHDL() as f:
        f.cond1 = BooleanSource(True)
        f.cond2 = BooleanSource(False)
        f.value = IntSource(100)
        f.result = f.value.if_(f.cond1).if_(f.cond2)

    f.run_until_complete()
    print(f"Result is skipped: {f.result.is_skipped((0,))}")


def example_6_conditional_branches():
    """Example 6: Different processing paths based on conditions."""
    print("\n=== Example 6: Conditional branches ===")

    with FlowHDL() as f:
        f.use_doubling = BooleanSource(True)
        f.use_adding = BooleanSource(False)
        f.value = IntSource(10)

        # Branch 1: Double the value if enabled
        f.doubled = Multiply(f.value, 2).if_(f.use_doubling)

        # Branch 2: Add 100 if enabled
        f.added = Add(f.value, 100).if_(f.use_adding)

        # Print both (only non-skipped will actually print)
        f.result1 = Print("Doubled", f.doubled)
        f.result2 = Print("Added", f.added)

    f.run_until_complete()

    print(f"Doubled branch executed: {not f.result1.is_skipped((0,))}")
    print(f"Added branch executed: {not f.result2.is_skipped((0,))}")


if __name__ == "__main__":
    print("=== Conditional Execution Demo ===")

    example_1_basic_propagate_if()
    example_2_if_method()
    example_3_skip_propagation()
    example_4_chaining()
    example_5_multiple_conditions()
    example_6_conditional_branches()

    print("\n=== Demo complete! ===")
