-------------------- MODULE FanOut3_Mono_CyclicStreamEx --------------------
(*
 * Test: A (streaming producer) -> B (mono consumer)
 *                              -> C (mono consumer)
 * 
 * A yields streaming values, then returns.
 * B and C wait for A's mono output (run level 0), then run.
 * 
 * Expected behavior:
 *   1. B or C demanded, solver finds A (stale edges A->B, A->C)
 *   2. A yields <<0,0>>, <<0,1>>, ... (B and C still can't start - edges stale at level 0)
 *   3. A returns <<0>> (mono complete)
 *   4. B and C can now start (edges fresh at level 0)
 *   5. B and C return <<0>>
 *
 * This tests fanout: one streaming producer feeding multiple mono consumers.
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

\* Fanout graph: A -> B, A -> C
FanoutEdges == {<<0, 1>>, <<0, 2>>}

\* No cycles, so no break edges needed
FanoutBreakEdges == {}

\* Edges A->B and A->C have minRunLevel=0 (B and C are mono consumers)
FanoutMinRunLevel == [e \in FanoutEdges |-> 0]

ConcreteNodes == {0, 1, 2}
ConcreteEdges == FanoutEdges
ConcreteBreakEdges == FanoutBreakEdges
ConcreteMinRunLevel == FanoutMinRunLevel

=============================================================================
