# Pytest

from collections.abc import AsyncGenerator

from flowno import node


@node
async def Constant() -> int:
    return 42


@node
async def ConstantStream() -> AsyncGenerator[str, None]:
    for i in range(3):
        yield str(i)


@node
async def Identity(x: int) -> int:
    return x


def test_case_1():
    """This is a simple test cases for a node with no input ports being run for the first time."""
    constant = Constant()._blank_finalized()

    assert constant.generation is None
    assert constant.get_data() is None

    constant.push_data((42,))

    assert constant.generation == (0,)
    assert constant.get_data(run_level=0) == (42,)


def test_case_2():
    """This is a simple test cases for a node with no input ports being run twice"""
    constant = Constant()._blank_finalized()

    constant.push_data((42,))
    constant.push_data((43,))

    assert constant.generation == (1,)
    assert constant.get_data(run_level=0) == (43,)


def test_case_3():
    """Test a node with no input ports starting a stream (pushing data at run level 1)."""

    # this could be done with a Constant node, but I want to use a node that actually produces a stream
    constant_stream = ConstantStream()._blank_finalized()

    assert constant_stream.generation is None
    assert constant_stream.get_data(run_level=0) is None
    assert constant_stream.get_data(run_level=1) is None

    # simulate the node being executed
    constant_stream.push_data(("0",), run_level=1)

    assert constant_stream.generation == (0, 0)
    assert constant_stream.get_data(run_level=0) is None
    assert constant_stream.get_data(run_level=1) == ("0",)

    constant_stream.push_data(("1",), run_level=1)
    constant_stream.push_data(("2",), run_level=1)

    assert constant_stream.generation == (0, 2)
    assert constant_stream.get_data(run_level=0) is None
    assert constant_stream.get_data(run_level=1) == ("2",)


def test_case_4():
    """Test a node with no inputs ending and restarting a stream."""

    constant_stream = ConstantStream()._blank_finalized()

    constant_stream.push_data(("0",), run_level=1)
    constant_stream.push_data(("1",), run_level=1)
    constant_stream.push_data(("2",), run_level=1)

    assert constant_stream.generation == (0, 2)
    assert constant_stream.get_data(run_level=0) is None
    assert constant_stream.get_data(run_level=1) == ("2",)

    # end the stream and push a final 'total' value
    constant_stream.push_data(("012",), run_level=0)

    # (0,) is the final value of the stream of partial values (0, 0), (0, 1), (0, 2)...(0, n)
    assert constant_stream.generation == (0,)
    assert constant_stream.get_data(run_level=0) == ("012",)
    # >>>> I need to think about this assertion. Should older streamed values be accessible after the stream ends?
    assert constant_stream.get_data(run_level=1) is None
    # <<<<

    # restart the stream
    constant_stream.push_data(("0",), run_level=1)

    assert constant_stream.generation == (1, 0)
    assert constant_stream.get_data(run_level=0) == ("012",)
    assert constant_stream.get_data(run_level=1) == ("0",)
