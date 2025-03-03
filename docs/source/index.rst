.. role:: python(code)
   :language: python

Flowno Documentation
====================

Welcome to the Flowno documentation!
Flowno is an embedded python DSL for making concurrent, cyclic, branching, and
streaming dataflow programs. It combines a functional node definition
syntax (:py:deco:`node <flowno.node>`) with a declarative flow descriptions (:python:`with FlowHDL() as f:`).
Though still a work in progress, my goal is to make LLM agent design easy and
modular.

.. hint::

   Almost all the classes, types and functions referenced in this documentation are internal or external hyperlinks. Try clicking on them to explore! Ex: :py:class:`~collections.abc.Coroutine`



Features
--------
Dataflow Evaluation 
    Automatically schedules nodes based on data dependencies.
Streaming Data
    Uses asynchronous generators for pipelining the processing of partial results.
Custom Event Loop
    Uses async/await syntax for non-blocking execution and concurrency. All nodes run concurrently by default (subject to data dependency constraints).
Declarative Connections
    Use the `FlowHDL` context manager to describe complex graphs,
    including cycles.

.. warning::
   Flowno does **not** use and is not compatible with the built-in ``asyncio`` event loop.
   If you see ``import asyncio`` in your code, you are mixing concurrency models, which is
   likely incorrect. Ensure you understand Python's ``async``/``await`` syntax at a high
   level—but do **not** expect Flowno nodes to run concurrently with asyncio tasks. *(This may change in the future.)*

Below is a quick demonstration of Flowno's node syntax, streaming, concurrency, and the ``FlowHDL`` description context:

.. testcode::

    from flowno import node, FlowHDL, sleep, Stream, azip

    @node
    async def Range(start: int, end: int):
        print(f"Range started: {start}..{end}")
        for i in range(start, end):
            await sleep(1.0)
            yield i

    @node(stream_in=["left", "right"])
    async def AddPiecewise(left: Stream[int], right: Stream[int]):
        async for l_item, r_item in azip(left, right):
            print(f"{l_item} + {r_item}")
            yield l_item + r_item

    @node(stream_in=["stream"])
    async def Sum(stream: Stream[int]) -> int:
        total = 0
        async for item in stream:
            print(f"{item}")
            await sleep(1.0)
            total += item 
        print(f"total: {total}")
        return total

    def main():
        with FlowHDL() as f:
            f.range_a = Range(0, 3)
            f.range_b = Range(100, 103)
            f.total = Sum(AddPiecewise(f.range_a, f.range_b))
        f.run_until_complete()  # takes 4 seconds to complete

    main()

Should produce the following output over 4 seconds:

.. testoutput::

    Range started: 0..3
    Range started: 100..103
    0 + 100
    100
    1 + 101
    102
    2 + 102
    104
    total: 306


.. admonition:: Naming Convention

   The function names here are capitalized because :py:deco:`node <flowno.node>` decorated functions
   behave similarly to classes (class factories).

Next Steps
----------
.. toctree::
   :maxdepth: 1

   user_guide/index
   developer_guide/index


License
-------
Flowno is licensed under the MIT License.

