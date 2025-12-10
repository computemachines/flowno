-------------------------- MODULE SimpleFlowDiamondEx --------------------------
(*
 * SimpleFlow instantiation with a diamond graph for testing.
 * Diamond: 0 -> 1, 0 -> 2, 1 -> 3, 2 -> 3
 *)
EXTENDS SimpleFlow

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}

=============================================================================
