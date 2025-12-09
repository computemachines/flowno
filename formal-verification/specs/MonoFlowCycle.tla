---------------------------- MODULE MonoFlowCycle ----------------------------
(*
 * MonoFlow instantiation with a cyclic graph for testing.
 *)
EXTENDS MonoFlow

CycleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}

=============================================================================
