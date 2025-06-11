Conditional Nodes
=================

The class :class:`~flowno.core.node_base.PropagateIf` passes through its input
only when a predicate is truthy. Draft nodes have a convenience method
:meth:`~flowno.core.node_base.DraftNode.if_` to insert ``PropagateIf`` before a
node and reconnect existing edges. Groups expose the same helper via
:meth:`~flowno.core.group_node.DraftGroupNode.if_`.

These helpers resolve forward references correctly, so they can be used inside a
``FlowHDL`` block just like regular node constructors.
