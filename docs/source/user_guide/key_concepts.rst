.. role:: python(code)
   :language: python

Key Concepts
============

Flowno is a tool for making dataflow programs\ [#f1]_. It shares many concepts
with reactive programming\ [#f2]_. A flowno *flow* follows some simple
behavior:

1. When a node evaluates, it triggers all of its dependent downstream nodes to
   evaluate next given the new data. 
2. Before a node evaluates, it recursively ensures all of its inputs are newer
   than its most recent evaluation, waiting until its inputs are fresh.
3. Cycles or feedback loops in the flow are bootstrapped by default argument
   values.

The entire flow is kept in lockstep by the internal, incrementing, per-node,
*generation* value. See :doc:`../developer_guide/index` for more details.

.. _stateless_nodes:

Stateless Nodes
---------------

The :py:deco:`node <flowno.node>` decorator transforms an :python:`async` function
into a :py:class:`DraftNode` subclass factory. When you call the decorated
function, it returns a :py:class:`DraftNode` instance configured with the
connections to other nodes or constant values.

.. code-block:: python

    @node
    async def Sum(x, y):
        return x + y

    # Sum is a class factory. Create two draft-node instances.
    sum_node1 = Sum(1, 2)  # Will always compute 1 + 2
    sum_node2 = Sum()      # Must be connected to other nodes before running

.. _stateful_nodes:

Stateful Nodes
--------------

Nodes can also be stateful—maintaining internal state across multiple calls.
This is useful for remembering previous inputs or outputs. Class variables set
inside :py:deco:`node` decorated classes are copied to the instances, similar
to dataclasses.

.. code-block:: python

    from flowno import node

    @node
    class RollingSum:
        total = 0

        async def call(self, x):
            self.total += x
            return self.total

    # rolling_sum has a private `total` attribute.
    rolling_sum = RollingSum(10)  # Returns 10 the first time, 20 the second time, etc.

FlowHDL Context Manager
-----------------------

The ``FlowHDL`` context is where you define how nodes connect to each other. It
also "finalizes" the nodes, replacing :py:class:`DraftNode` instances with
fully specified :py:class:`Node` instances.

.. code-block:: python

    with FlowHDL() as f:
        f.node_x = Sum(1, 2)
        f.node_y = Sum(f.node_x, 3)
        # here, f.node_x and f.node_y are DraftNode instances

    # here, f.node_x and f.node_y are now Node instances

    f.run_until_complete()
    f.node_y.get_data()  # Returns (6,)

The ``FlowHDL`` context allows referencing nodes before they are defined, which
is necessary for describing cyclic dependencies.

.. code-block:: python

    with FlowHDL() as f:
        f.node_y = Sum(f.node_x, 3)  # This is fine
        f.node_x = Sum(1, 2)
    
    f.run_until_complete()
    f.node_y.get_data()  # Still returns (6,)

Cycle Breaking
--------------

Consider a simple cycle sketched out below:

.. uml::

   @startuml
   component [""f.a""] as a <<Increment>>
   component [""f.b""] as b <<Double>>
   a -> b: value
   b -> a: value
   @enduml

We can describe it in Flowno, no problem! That is the purpose of the somewhat
awkward :python:`with FlowHDL() as f:` block.

.. testcode::

    from flowno import node, FlowHDL, TerminateLimitReached

    @node
    async def Increment(value: int) -> int:
        return value + 1

    @node
    async def Double(value: int) -> int:
        return value * 2

    with FlowHDL() as f:
        f.a = Increment(f.b)
        f.b = Double(f.a)

    f.run_until_complete()
    
However, there is a problem. Flowno doesn't know which node should be executed
first, or what the initial 'bootstrapped' value should be. If we run this, we
get the following exception:

.. testoutput::

    Traceback (most recent call last):
    ...
    flowno.core.node_base.MissingDefaultError: Detected a cycle without default values. You must add defaults to the indicated arguments for at least ONE of the following nodes:
      Double#0 must have defaults for EACH/ALL the underlined parameters:
      Defined at <doctest default[0]>:7
      Full Signature:
      async def Double(value: int)
                       ---------- 
    OR
      Increment#0 must have defaults for EACH/ALL the underlined parameters:
      Defined at <doctest default[0]>:3
      Full Signature:
      async def Increment(value: int)
                          ----------

The exception is trying to tell you that you need to break the cycle somewhere
by adding a default value to :python:`Double` *or* :python:`Increment`. I'll
add a default value of 0 to the increment node, then add some print statements
so we can see what is happening. Finally, I'll use the
``stop_at_node_generation`` for testing to stop the flow if any node's generation
exceeds some arbitrary value.

.. testcode::

    from flowno import node, FlowHDL, TerminateLimitReached

    @node
    async def Increment(value: int = 0) -> int:
        print(f"Increment({value}) => {value+1}")
        return value + 1

    @node
    async def Double(value: int) -> int:
        print(f"Double({value}) => {value*2}")
        return value * 2

    with FlowHDL() as f:
        f.a = Increment(f.b)
        f.b = Double(f.a)

    try:
        f.run_until_complete(stop_at_node_generation=(3,))
    except TerminateLimitReached:
        print("Finished Normally")

.. testoutput::

    Increment(0) => 1
    Double(1) => 2
    Increment(2) => 3
    Double(3) => 6
    Increment(6) => 7
    Double(7) => 14
    Increment(14) => 15
    Finished Normally

As you can see, the cycle starts with ``Increment(0)``, runs through the loop a
couple of times then finishes. You probably shouldn't use
``stop_at_node_generation`` outside of testing, instead explicitly raising an
exception when you want a cyclic flow to terminate.

.. _streaming_nodes:

.. _mono_nodes:

.. _streaming_inputs:

.. admonition:: TODO

   Explain Streaming inputs vs outputs

   Explain Streaming node vs mononode

.. rubric:: Read More

.. [#f1] https://en.wikipedia.org/wiki/Dataflow_programming
.. [#f2] https://en.wikipedia.org/wiki/Reactive_programming
