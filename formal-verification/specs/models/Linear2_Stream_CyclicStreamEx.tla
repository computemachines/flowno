-------------------- MODULE Linear2_Stream_CyclicStreamEx --------------------
(*
 * Test: A (streaming producer) -> B (streaming consumer with minRunLevel=1)
 * 
 * A yields streaming values, then returns.
 * B can start as soon as A yields (run level 1 data available).
 * 
 * Expected behavior:
 *   1. B demanded, solver finds A (stale edge A->B)
 *   2. A yields <<0,0>>
 *   3. B can now start (edge fresh at level 1)
 *   4. Interleaved execution of A and B yields
 *   5. Eventually both return
 *
 * Note: This model does NOT yet handle B stalling when it needs more data
 * from A. That requires the stall/wake actions we deferred.
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

\* Simple linear graph: A -> B
SimpleEdges == {<<0, 1>>}

\* No cycles, so no break edges needed
SimpleBreakEdges == {}

\* Edge A->B has minRunLevel=1 (B is streaming consumer)
StreamingMinRunLevel == [e \in SimpleEdges |-> 1]

ConcreteNodes == {0, 1}
ConcreteEdges == SimpleEdges
ConcreteBreakEdges == SimpleBreakEdges
ConcreteMinRunLevel == StreamingMinRunLevel

=============================================================================
