-------------------- MODULE FanOut3_Stream_CyclicStreamEx --------------------
(*
 * Test: A (streaming producer) -> B (streaming consumer with minRunLevel=1)
 *                              -> C (streaming consumer with minRunLevel=1)
 * 
 * A yields streaming values, then returns.
 * B and C can start as soon as A yields (run level 1 data available).
 * 
 * Expected behavior:
 *   1. B or C demanded, solver finds A (stale edges A->B, A->C)
 *   2. A yields <<0,0>>
 *   3. B and C can now start (edges fresh at level 1)
 *   4. Interleaved execution of A, B, and C yields
 *   5. Eventually all three return
 *
 * This tests fanout: one streaming producer feeding multiple streaming consumers.
 *
 * Note: This model does NOT yet handle B or C stalling when they need more data
 * from A. That requires the stall/wake actions we deferred.
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

\* Fanout graph: A -> B, A -> C
FanoutEdges == {<<0, 1>>, <<0, 2>>}

\* No cycles, so no break edges needed
FanoutBreakEdges == {}

\* Edges A->B and A->C have minRunLevel=1 (B and C are streaming consumers)
FanoutMinRunLevel == [e \in FanoutEdges |-> 1]

ConcreteNodes == {0, 1, 2}
ConcreteEdges == FanoutEdges
ConcreteBreakEdges == FanoutBreakEdges
ConcreteMinRunLevel == FanoutMinRunLevel

=============================================================================
