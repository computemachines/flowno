-------------------- MODULE FanIn3_Stream_CyclicStreamEx --------------------
(*
 * Test: A (streaming producer) -> C (streaming consumer with minRunLevel=1)
 *       B (streaming producer) -> C (streaming consumer with minRunLevel=1)
 * 
 * A and B yield streaming values, then return.
 * C can start as soon as both A and B have yielded (run level 1 data available).
 * 
 * Expected behavior:
 *   1. C demanded, solver finds A and B (stale edges A->C, B->C)
 *   2. A yields <<0,0>> (edge A->C fresh at level 1)
 *   3. B yields <<0,0>> (edge B->C fresh at level 1)
 *   4. C can now start (both edges fresh at level 1)
 *   5. Interleaved execution of A, B, and C yields
 *   6. Eventually all three return
 *
 * This tests fan-in: multiple streaming producers feeding one streaming consumer.
 *
 * Note: This model does NOT yet handle C stalling when it needs more data
 * from A or B. That requires the stall/wake actions we deferred.
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

\* Fan-in graph: A -> C, B -> C
FaninEdges == {<<0, 2>>, <<1, 2>>}

\* No cycles, so no break edges needed
FaninBreakEdges == {}

\* Edges A->C and B->C have minRunLevel=1 (C is streaming consumer)
FaninMinRunLevel == [e \in FaninEdges |-> 1]

ConcreteNodes == {0, 1, 2}
ConcreteEdges == FaninEdges
ConcreteBreakEdges == FaninBreakEdges
ConcreteMinRunLevel == FaninMinRunLevel

=============================================================================
