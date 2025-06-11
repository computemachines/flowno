.. role:: python(code)
   :language: python

****************************
Conditional Execution
****************************

Flowno can skip parts of a flow based on runtime conditions. The helper
:meth:`~flowno.core.node_base.DraftNode.if_` inserts a
:class:`~flowno.core.node_base.PropagateIf` node before the current node.
The node still resolves its inputs, but its own execution is gated by the
predicate value.

Example
=======

.. testcode::

   from flowno import node, FlowHDL

   @node
   async def AddOne(x: int) -> int:
       return x + 1

   @node
   async def IsEven(x: int) -> bool:
       return x % 2 == 0

   with FlowHDL() as f:
       f.val = AddOne(1).if_(IsEven(2))

   f.run_until_complete()
   print(f.val.get_data())

.. testoutput::

   (2,)

``DraftGroupNode`` provides a similar :py:meth:`~flowno.core.group_node.DraftGroupNode.if_`
method. It wraps the entire group with ``PropagateIf`` so all internal nodes
run but their output is gated.
