-------------------- MODULE FaninStreamingProducerMonoConsumerEx --------------------
(*
 * Test: A (streaming producer) -> C (mono consumer)
 *       B (streaming producer) -> C (mono consumer)
 * 
 * A and B yield streaming values, then return.
 * C waits for both A's and B's mono output (run level 0), then runs.
 * 
 * Expected behavior:
 *   1. C demanded, solver finds A and B (stale edges A->C, B->C)
 *   2. A yields <<0,0>>, <<0,1>>, ... (C still can't start - edge A->C stale at level 0)
 *   3. B yields <<0,0>>, <<0,1>>, ... (C still can't start - edge B->C stale at level 0)
 *   4. A returns <<0>> (mono complete on A->C)
 *   5. B returns <<0>> (mono complete on B->C)
 *   6. C can now start (both edges fresh at level 0)
 *   7. C returns <<0>>
 *
 * This tests fan-in: multiple streaming producers feeding one mono consumer.
 *)
EXTENDS CyclicStreamingFlow

\* Fan-in graph: A -> C, B -> C
FaninEdges == {<<0, 2>>, <<1, 2>>}

\* No cycles, so no break edges needed
FaninBreakEdges == {}

\* Edges A->C and B->C have minRunLevel=0 (C is mono consumer)
FaninMinRunLevel == [e \in FaninEdges |-> 0]

=============================================================================
