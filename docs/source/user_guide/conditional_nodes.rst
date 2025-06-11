.. role:: python(code)
   :language: python

Conditional Nodes
=================

Sometimes a flow should run certain nodes only when a condition is true.  The
:py:meth:`~flowno.core.node_base.DraftNode.if_` and
:py:meth:`~flowno.core.group_node.DraftGroupNode.if_` helpers insert a
:py:class:`~flowno.core.node_base.PropagateIf` node that gates execution based on
``predicate``.

When the predicate is ``False`` the upstream node or group is skipped and no
outputs are propagated to dependent nodes.

Example usage for a single node:

.. testcode::
   :hide:

   import os
   os.environ["FLOWNO_LOG_LEVEL"] = "ERROR"

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