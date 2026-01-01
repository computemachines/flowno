"""Debug script to reproduce the orphaned anonymous node issue."""
import logging
from flowno import FlowHDL, node
from typing import TypeVar

T = TypeVar("T")

# Define nodes used in the test
@node
async def Identity(x: T) -> T:
    return x

@node
async def Add(x: int, y: int = 0) -> int:
    return x + y

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)-8s %(name)-30s %(message)s'
)

def main():
    print("=" * 80)
    print("Creating flow with orphaned anonymous node")
    print("=" * 80)

    with FlowHDL() as f:
        # Create an anonymous Add node not connected to anything
        print("\nCreating Add(1, 2) - anonymous, not used")
        Add(1, 2)

        # Named node that we'll actually use
        print("Creating f.result = Identity(42)")
        f.result = Identity(42)

    print("\n" + "=" * 80)
    print("Running flow")
    print("=" * 80 + "\n")

    f.run_until_complete()

    print("\n" + "=" * 80)
    print("Flow completed")
    print("=" * 80)

    result = f.result.get_data()
    print(f"\nf.result.get_data() = {result}")
    print(f"Expected: (42,)")
    print(f"Match: {result == (42,)}")

    if result != (42,):
        print("\n❌ FAILURE: Result doesn't match!")
        return 1
    else:
        print("\n✅ SUCCESS: Result matches!")
        return 0

if __name__ == "__main__":
    exit(main())
