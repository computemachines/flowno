
=========================================================
Flowno Internals: Flow Execution and Resolution Mechanics
=========================================================

This document provides a technical deep dive into the internal mechanics of
Flowno, focusing on how flows are executed, how data dependencies are resolved,
and how cycles are handled. It is intended for **library contributors** and
**developers debugging complex flows**. If you're new to Flowno, start with the
`README <../README.md>`_ for an overview of the library's features and
`Walkthrough <../walkthrough_guide.md>`_ for a step-by-step guide to the process
of constructing a non-trivial flow.



.. contents::
  :local:
  :depth: 2

1. Flow Overview
----------------

1.1 Dataflow Model
~~~~~~~~~~~~~~~~~~

Flowno is built around a **dataflow programming model**, where computations are
represented as nodes connected by data dependencies. Nodes are executed when
their inputs are ready, and their outputs trigger downstream nodes. This model
enables **concurrency**, **streaming**, and **cyclic dependencies**. In a
tangled web of nodes, Flowno schedules the concurrent execution of nodes in the
optimal way to preserve the proper ordering of each node's neighbors.

1.2 Key Components
~~~~~~~~~~~~~~~~~~

- **Nodes**: The basic units of computation. Nodes can be stateless (pure
  functions) or stateful (classes with internal state). They are defined with
  the ``@node`` decorator and finalized by the ``FlowHDL`` context.

- **FlowHDL Context**: A declarative way to construct and connect nodes. Nodes
  are instantiated and connected within a ``with FlowHDL() as f:`` block.

- **Event Loop**: The concurrency is provided by a custom event loop, not
  threads or ``asyncio``. It is a completely separate concurrency model. This is
  emphasized because Flowno uses Python’s ``async/await`` syntax similarly to
  Asyncio, but is incompatible with Asyncio. (see 
  `Common Pitfalls <../flowno_pitfalls.md>`_)

1.3 Types and Constructing Nodes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Nodes are defined using the ``@node`` decorator on async functions. By convention,
they are capitalized like classes because they behave like classes, constructing
``NodeBase`` subclassed objects.

.. code-block:: python

   @node
   async def SomeNode(string_input: str):
       # do something
       return 42 

   reveal_type(SomeNode)  # type[DraftNode1[str, tuple[int]]]
   a = SomeNode("hello")  # create some nodes; does not execute
   b = SomeNode("worlds")
   reveal_type(a)  # DraftNode1[str, tuple[int]]

``DraftNode1`` is a generic type only visible during typechecking.

1.4 Connecting Nodes during Instantiation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These node objects are connected together by passing dependencies into the node
constructor. The type checker reports when incompatible nodes are connected. For
example, ``SomeNode(SomeNode("hello"))`` tries to pass an integer output
(``42``) to a node expecting a string.

.. code-block:: python

   @node
   async def SomeIntNode(int_input: int):
       # do something with the input
       pass
       # returns nothing

   reveal_type(SomeIntNode)  # type[DraftNode1[int, tuple[None]]]
   a = SomeNode("hello")
   c = SomeIntNode(a)  # ok
   d = SomeNode(a)     # type error

There is a ``connect`` method for forming connections after node instantiation,
but typically you don’t need it.

1.5 FlowHDL Context
~~~~~~~~~~~~~~~~~~~

The ``FlowHDL`` context is the mechanism for defining circular dependencies
without resorting to the ``connect`` method. Example:

.. code-block:: python

   @node
   async def IntToStr(value: int):
       return str(value)

   with FlowHDL() as f:
       f.a = SomeNode(f.b)
       f.b = IntToStr(f.a)

The ``FlowHDL`` returns ``NodePlaceholder`` objects when accessing an attribute
that is not yet defined on the context. When the context exits, the nodes
defined on the context are finalized, replacing placeholders with actual node
connections. This allows you to reference a node before it is defined, which is
necessary for describing cycles.

A side effect of this behavior is that statements can be in any order, similarly
to the ``<=`` operator in hardware description languages. For instance:

.. code-block:: python

   with FlowHDL() as f:
       f.b = IntToStr(f.a)  # f.a is a placeholder here
       f.a = SomeNode(f.b)

returns a flow with identical behavior to a version in which the lines are
reversed.

1.6 Executing the Flow
~~~~~~~~~~~~~~~~~~~~~~

The flow must be “finalized” before it can run. The ``with`` block raises an
exception if a nonexistent node output is connected or if a node was referenced
but never defined. Exiting the block finalizes and replaces ``DraftNode`` objects
with actual ``Node`` types:

.. code-block:: python

   with FlowHDL() as f:
       f.node_instance = MyNode()
       assert isinstance(f.node_instance, DraftNode)
   # the context exits and finalizes f.node_instance
   assert isinstance(f.node_instance, Node)

Starting the flow happens **outside** the ``with`` block:

.. code-block:: python

   f.run_until_complete()

If any node raises an uncaught exception, the whole flow terminates, and the
exception propagates.

1.7 Some Definitions
~~~~~~~~~~~~~~~~~~~~

DraftNode
    A node constructed by an ``@node``-decorated class factory or class.

Functional Node:
  A node defined by an ``@node``-decorated async function.

Stateful Node:
  A node defined by an ``@node``-decorated class.

Node:
  Generally refers to any node that has been finalized by a
  ``FlowHDL`` context.

Mono-Node:
  A node that does not stream values out.

Streaming Node / Streaming-out Node:
  A node that uses the ``yield`` keyword to produce partial chunks.

Streaming-input Node:
  A node that marks an input as requiring a streaming input using
  ``@node(stream_in=[...])``. Such a node does not need to stream out; it
  could still return a single value.

2. Execution Order Intuition
----------------------------

2.1 Basic Rule: Dependencies Run Before Dependents
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In Flowno, a node executes **when its inputs (dependencies) are “fresher” than
its own last run**. If an input is stale, Flowno recursively attempts to execute
that stale input node first. The ``f.run_until_complete()`` method picks an
arbitrary node to start.

**Example: Linear Chain**

.. code-block:: python

   @node
   async def MyNode0():
       ...

   @node
   async def MyNode(value):
       ...

   with FlowHDL() as f:
       f.a = MyNode0()
       f.b = MyNode(f.a)  # f.b depends on f.a
       f.c = MyNode(f.b)  # f.c depends on f.b
   f.run_until_complete()

*Execution order* remains consistent even if Flowno picks a different node first.

.. uml::

   @startuml
   hide empty description
   [*] --> a
   a -> b
   b -> c
   c --> [*]
   @enduml

2.2 Basic Rule: Everything That Can Run Concurrently, Does
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   with FlowHDL() as f:
       f.a = MyNode()

       f.b1 = MyNode(f.a)
       f.b2 = MyNode(f.b1)
       f.c = MyNode(f.a)

When ``a`` fans out, both ``c`` and ``b`` can run in parallel. Flowno computes an
activity diagram based on the data dependencies:

.. uml::

   @startuml
   hide empty description
   left to right direction
   state a_f <<fork>>
   [*] -down-> a
   a -down-> a_f
   a_f -down-> b1
   b1 -down-> b2
   a_f -down-> c
   state final <<fork>>
   c --down-> final
   b2 -down-> final
   final -down-> [*]
   @enduml

Internally, it behaves similarly to explicit concurrency:

.. code-block:: python

   from flowno import spawn

   async def main():
       a_result = await my_node_work()
       async def branch_b():
           b1_result = await my_node_work(a_result)
           b2_result = await my_node_work(b1_result)
           return b2_result

       branch_b_task = await spawn(branch_b())
       branch_c_task = await spawn(my_node_work(a_result))

       b2_result = await branch_b_task.join()
       c_result = await branch_c_task.join()

2.3 Basic Rule: Cycles are Bootstrapped by Default Arguments
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you have a DAG (Directed Acyclic Graph), a topological sort suffices. But
when cycles exist, you need a mechanism to “break” them. In Flowno, that
mechanism is the *default argument* on at least one node input.

**Example: Simple Feedback Loop**

.. code-block:: python

   @node
   async def MyNodeWithDefault(value="default"):
       ...

   with FlowHDL() as f:
       f.a = MyNode(f.c)
       f.b = MyNodeWithDefault(f.a)
       f.c = MyNode(f.b)

In a multi-cycle network or with streaming data, Flowno’s scheduling becomes more
valuable.

.. uml::

   hide empty description
   state a
   [*] -> b
   a -> b
   c -> a
   b -> c

2.4 Basic Rule: Each Node Executes the Same Number of Times
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A key consequence of Flowno’s resolution algorithm is that **all nodes evaluate
the same number of times**. Even nodes that generate streaming data (run level 1
data) ultimately produce final data at run level 0 in lockstep.

.. code-block:: python

   async def MyNodeWithSelfLoop(value1, old_value=None):
       ...

   with FlowHDL() as f:
       f.a = MyNodeWithDefault(f.c)
       f.b = MyNodeWithSelfLoop(f.a, f.c)
       f.c = MyNode(f.b)

       .. uml::

   @startuml
   title Component Diagram (Data Flows)
   component """f.a""" as a <<MyNodeWithDefault>>
   component """f.b""" as b <<MyNodeWithSelfLoop>>
   component """f.c""" as c <<MyNode>>
   a -> b
   b --> c
   b -> b
   c -> a
   @enduml

   .. uml::

   @startuml
   hide empty description
   title Activity Diagram (Execution Ordering)
   state a
   state b
   state c
   [*] -> a
   a -> b
   b --> c
   c -> a
   @enduml

2.5 Basic Rule: Streams are Pipelined
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A node with a streaming output won’t continue until all consumers read its most
recent output. If a consumer stalls, the producer is paused.

.. code-block:: python

   from flowno import Stream

   @node
   async def MyStreamOutNode():
       yield "Hello"
       yield " Worlds"

   @node(stream_in=["words"])
   async def MyStreamInOutNode(words: Stream[str]):
       async for word in words:
           yield word.upper()

   @node(stream_in=["words"])
   async def MyStreamInNode(words: Stream[str]):
       async for word in words:
           print(word, end="")
       print()

   with FlowHDL() as f:
       f.producer = MyStreamOutNode()
       f.transform = MyStreamInOutNode(f.producer)
       f.consumer = MyStreamInNode(f.transform)

.. uml::

   @startuml
   title Component Diagram (Data Flows)
   component """f.producer""" as a <<MyStreamOutNode>>
   component """f.transform""" as b <<MyStreamInOutNode>>
   component """f.consumer""" as c <<MyStreamInNode>>
   a .> b: "words: Stream[str]"
   b .> c: "words: Stream[str]"
   @enduml

Below is the actual event flow as Flowno juggles control among these nodes:

.. uml::

   @startuml
   control "Flowno Event Loop" as Scheduler
   participant Producer
   participant Transform
   participant Consumer

   [o-> Scheduler: "f.run_until_complete()"
   activate Scheduler

   Scheduler -> Producer: <<start>>
   activate Producer

   Producer -> Scheduler: yield "Hello"
   deactivate Producer

   Scheduler -> Transform: <<start>>
   activate Transform

   Transform -> Scheduler: await anext(stream)
   activate Scheduler
   return "Hello"
   Transform -> Scheduler: yield "HELLO"
   deactivate

   Scheduler -> Consumer: <<start>>
   activate Consumer

   Consumer -> Scheduler: await anext(stream)
   activate Scheduler
   return "HELLO"
   Consumer ->o] : print "HELLO"

   Consumer -> Scheduler: await anext(stream)
   deactivate Consumer
   activate Scheduler
   Scheduler -> Scheduler: Consumer Stalled
   deactivate

   Scheduler -> Transform: <<continue>>
   activate Transform
   Transform -> Scheduler: await anext(stream)
   deactivate Transform
   activate Scheduler
   Scheduler -> Scheduler: Transform Stalled
   deactivate

   Scheduler -> Producer: <<continue>>
   activate Producer
   Producer -> Scheduler: yield " Worlds"
   deactivate Producer

   Scheduler -> Transform: <<continue>>
   activate Transform
   Transform -> Scheduler: await anext(stream)
   activate Scheduler
   return " Worlds"
   Transform -> Scheduler: yield " WORLDS"
   deactivate

   Scheduler -> Consumer: <<continue>>
   activate Consumer
   Consumer -> Scheduler: await anext(stream)
   activate Scheduler
   return "WORLDS"
   Consumer ->o] : print "WORLDS"
   Consumer -> Scheduler: await anext(stream)
   deactivate
   activate Scheduler
   Scheduler -> Scheduler: Consumer Stalled
   deactivate

   Scheduler -> Transform: <<continue>>
   activate Transform
   Transform -> Scheduler: await anext(stream)
   deactivate Transform
   activate Scheduler
   Scheduler -> Scheduler: Transform Stalled
   deactivate

   Scheduler -> Producer: <<continue>>
   activate Producer
   Producer -> Scheduler: raise StopAsyncIteration()
   destroy Producer
   note right
     Returning from an async generator
     raises a StopAsyncIteration.
   end note
   note left
     Implicitly Accumulate
     ("HELLO WORLDS",).
     However, none of these
     nodes use the accumulated
     final value.
   end note

   Scheduler -> Transform: <<continue>>
   activate Transform
   Transform -> Scheduler: await anext(stream)
   activate Scheduler
   return inject StopAsyncIteration()
   note right
     Injecting a StopAsyncIteration
     exception breaks the node out of
     the async for loop.
   end note
   Transform -> Scheduler: raise StopAsyncIteration()
   note right
     After the async generator finishes
     it raises its own StopAsyncIteration
     exception.
   end note
   note left
     Implicitly accumulate
     ("HELLO WORLDS",).
     Consumer only uses the
     streamed (run level 1)
     values, not the final
     (run level 0 value)
   end note
   destroy Transform

   Scheduler -> Consumer: <<continue>>
   activate Consumer
   Consumer -> Scheduler: await anext(stream)
   activate Scheduler
   return inject StopAsyncIteration()
   note right
     Breaks out of the
     async for loop
   end note
   Consumer ->o] : print newline
   Consumer -> Scheduler: return None
   note right
     This async function is
     not an AsyncGenerator,
     it returns a final value.
   end note
   note left
     Explicitly set final data
     (run level 0) to "()".
   end note
   destroy Consumer
   note over Scheduler
     There are no more nodes
     in the resolution queue.
   end note
   [o<-- Scheduler: return
   destroy Scheduler
   deactivate
   @enduml

From a node’s perspective, it feels like:

.. uml::

   @startuml
   participant Producer
   participant Transform
   participant Consumer

   activate Producer
   activate Transform
   activate Consumer
   Producer ->> Transform: "Hello"
   Transform ->> Consumer: "HELLO"
   Consumer ->o]: print "HELLO"
   Producer ->> Transform: " Worlds"
   destroy Producer
   Transform ->> Consumer: " WORLDS"
   destroy Transform
   Consumer ->o]: print " WORLDS"
   Consumer ->o]: print newline
   destroy Consumer
   @enduml

3. Generation Value
-------------------

3.1 Definition & Structure
~~~~~~~~~~~~~~~~~~~~~~~~~~

The **generation value** is a tuple of integers ``(main_gen, sub_gen_1, ...)``
that versions the data produced by a node. It helps determine execution order
and resolve dependencies. (Higher sub-generations may be used for streaming data
in subflows later.)

- ``main_gen``: Tracks the primary execution count, e.g. ``(0,)`` for the first
  final data produced by a node.
- ``sub_gen``: Tracks nested levels for streaming or partial results, e.g. 
  ``(1, 0)`` for the first chunk of the second run.
- **Run level**: The index of the last sub-generation. Regular data is run
  level 0; streaming data is run level 1.
- ``node.generation``: A getter property that returns the highest generation
  produced by the node. Each run increments the generation.

3.2 Intuition
~~~~~~~~~~~~~

As a node yields streaming output for the first time (e.g., "H
