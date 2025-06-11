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
   async def Double(x: int) -> int:
       return x * 2

   with FlowHDL() as f:
       f.result = Double(3).if_(True)

   f.run_until_complete()
   print(f.result.get_data())

.. testoutput::

   (6,)

The same approach works for template groups using
:py:meth:`~flowno.core.group_node.DraftGroupNode.if_`.
