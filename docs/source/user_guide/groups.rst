.. role:: python(code)
   :language: python

*****************
Group Templates
*****************

Flowno supports reusable subgraphs through **template groups**. A template is defined
with :py:deco:`node.template <flowno.node.template>` and behaves like a function
that builds a small :class:`FlowHDL` snippet. The first parameter must be a
:class:`FlowHDLView` which provides the temporary context used to create nodes
inside the group.

The template should return one of the nodes it defines. When the surrounding
:class:`FlowHDL` context is finalized the ``DraftGroupNode`` produced by calling
the template is replaced by that return value, leaving no trace of the template
at runtime.

Example
=======

.. testcode::

   from flowno import node, FlowHDL, FlowHDLView

   @node
   async def Inc(x: int) -> int:
       return x + 1

   @node.template
   def IncTwice(f: FlowHDLView, x: int):
       f.first = Inc(x)
       f.second = Inc(f.first)
       return f.second

   with FlowHDL() as f:
       f.result = IncTwice(1)

   f.run_until_complete()
   print(f.result.get_data())

.. testoutput::

   (3,)

Template groups may accept multiple inputs and default values just like normal
:py:deco:`node` functions. Groups can also be nested, allowing complex flows to
be composed from smaller pieces.

