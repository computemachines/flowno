-------------------------- MODULE Diamond4_Mono_ConcEx --------------------------
(*
 * SimpleFlow instantiation with a diamond graph for testing.
 * Diamond: 0 -> 1, 0 -> 2, 1 -> 3, 2 -> 3
 *)
EXTENDS SimpleConcurrentFlow

\* Use config: formal-verification/specs/model-tests/SimpleConcurrentFlow.cfg

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}

ConcreteNodes == {0, 1, 2, 3}
ConcreteEdges == DiamondEdges

=============================================================================
