import logging
from typing import Any, TypeVar, Union, cast, overload

from flowno import Flow, FlowHDL, node, TerminateLimitReached
from flowno.core.node_base import Constant, DraftInputPortRef, DraftNode
from flowno.core.types import Generation, InputPortIndex, OutputPortIndex
from pytest import raises
from typing_extensions import Unpack

logger = logging.getLogger(__name__)

T = TypeVar("T")


@node(multiple_outputs=True)
async def append(x: Union[str, None] = "", y: Union[str, None] = "") -> tuple[str,]:
    if x is None:
        x = ""
    if y is None:
        y = ""
    return (x + y,)


@node
async def Identity(x: T) -> T:
    return x


@node(multiple_outputs=True)
async def Constants() -> tuple[str, str, str]:
    return ("Left", "Center", "Right")


def test_create_flow():
    flow = Flow()
    assert flow


def test_add_nodes():
    flow = Flow()
    node1 = Identity()
    flow.add_node(node1)
    flow.add_nodes([node1])


def test_connect_nodes():
    flow = Flow()
    node1 = Identity()
    node2 = Identity()
    flow.add_nodes([node1, node2])
    node1.output(0).connect(node2.input(0))


def test_run_trivial_flow_explicit():
    flow = Flow()
    hdl = FlowHDL()
    hdl._flow = flow

    ctx = hdl.__enter__()
    node1 = Constants()
    ctx._nodes["node1"] = node1
    ctx.__exit__(None, None, None)

    finalized_node1 = hdl._nodes["node1"]

    flow.run_until_complete()
    assert finalized_node1.get_data() == ("Left", "Center", "Right")


@node
async def Looper(x: int = 0) -> int:
    return x + 1


def test_simple_loop():
    
    @node
    async def InnerLooper(x: int = 0) -> int:
        return x + 1

    with FlowHDL() as f:
        f.node1 = InnerLooper(f.node1.output(0))
    
    finalized_node1 = f.node1

    with raises(TerminateLimitReached):
        f._flow.run_until_complete(stop_at_node_generation={finalized_node1: (1,)})
    assert finalized_node1.get_data() == (2,)


def test_simple_flow_data_passing():
    with FlowHDL() as f:
        f.node1 = Constants()
        f.node2 = append(f.node1.output(0), f.node1.output(1))

    f.run_until_complete()
    assert f.node2.get_data() == ("LeftCenter",)


@node
async def can_fail() -> str:
    raise ValueError("This node always fails")


def test_simple_error_handling():
    with FlowHDL() as f:
        f.fail_node = can_fail()

    with raises(ValueError):
        f.run_until_complete()


def make_linear_flow():
    with FlowHDL() as flow:
        flow.node1 = Constant("Hello")
        flow.node2 = Identity(flow.node1)
        flow.node3 = Identity(flow.node2)

    return flow, (flow.node1, flow.node2, flow.node3)


@overload
def assert_node_generations(
    flow: FlowHDL,
    node: DraftNode[Unpack[tuple[Any, ...]], tuple[object, ...]],
    expected_generation: Generation,
) -> None: ...


@overload
def assert_node_generations(
    flow: FlowHDL,
    node: DraftNode[Unpack[tuple[Any, ...]], tuple[object, ...]],
    expected_generation: Generation,
    expected_nodes_to_force_evaluate: list[DraftNode[Unpack[tuple[Any, ...]], tuple[object, ...]]],
) -> None: ...


def assert_node_generations(
    flow: FlowHDL,
    node: DraftNode[Unpack[tuple[Any, ...]], tuple[object, ...]],
    expected_generation: Generation,
    expected_nodes_to_force_evaluate: Union[list[DraftNode[Unpack[tuple[Any, ...]], tuple[object, ...]]], None] = None,
):
    assert node.generation == expected_generation

    if expected_nodes_to_force_evaluate is not None:
        # assert node.get_inputs_with_le_generation() != []
        assert flow._flow._find_node_solution(node) == expected_nodes_to_force_evaluate
    else:
        # assert node.get_inputs_with_le_generation() == []
        pass


def test_force_evaluate_linear():
    flow, (node1, node2, node3) = make_linear_flow()
    node2.push_data(("Hello",))

    assert_node_generations(flow, node1, None)
    # node2 should have the newest generation
    # the dependecies of node2 should be stale
    # Following the chain of stale dependencies, we should find node1 as a leaf and no cycles to break
    assert_node_generations(flow, node2, (0,), [node1])
    assert_node_generations(flow, node3, None)


def make_circular_flow():
    with FlowHDL() as flow:
        flow.node1 = Identity(flow.node3)
        flow.node2 = Identity(flow.node1)
        flow.node3 = Identity(flow.node2)

    return flow, (flow.node1, flow.node2, flow.node3)


def test_force_evalutate_circular():
    flow, (node1, node2, node3) = make_circular_flow()

    node2.push_data(("Hello",))
    # only node2 has a generation > None

    # node1 depends on node3, which depends on node2, which depends on node1
    # find_nodes_to_force_evaluate should return a node from the cycle according to the rules
    assert_node_generations(flow, node1, None, [node3])
    assert_node_generations(flow, node2, (0,), [node3])
    assert_node_generations(flow, node3, None)


def test_condensed_tree_linear():
    flow, (node1, node2, node3) = make_linear_flow()

    supernode_root = flow._flow._condensed_tree(node2)

    # each node should be its own Strongly Connected Component
    # the condensed tree of SSCs should be the same as the original graph

    assert supernode_root.head == node2
    assert supernode_root.members == {node2: []}

    assert len(supernode_root.dependencies) == 1
    supernode_parent = supernode_root.dependencies.pop()
    assert supernode_parent.head == node1
    assert supernode_parent.members == {node1: []}

    assert len(supernode_parent.dependencies) == 0


def test_condensed_tree_circular():
    # Setup a circular flow with three nodes
    flow, (node1, node2, node3) = make_circular_flow()  # Adjust to create actual circular dependencies

    # Perform the condensed tree operation starting from any node, here node1
    supernode_circular = flow._flow._condensed_tree(node1)

    # Verify that all three nodes are part of the same SCC and thus in the same SuperNode
    assert supernode_circular.head in {node1, node2, node3}  # Head can be any node in the cycle
    assert supernode_circular.members == {node1: [0], node2: [0], node3: [0]}  # All nodes should be in the members set

    # Check that there are no external dependencies
    assert len(supernode_circular.dependencies) == 0  # No dependencies outside the cycle

    # Optionally check the internal structure if your SuperNode setup captures internal links
    # This part depends on whether your SuperNode or system captures such internal SCC links explicitly
