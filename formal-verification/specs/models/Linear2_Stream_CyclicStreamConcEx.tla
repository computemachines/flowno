------------------------ MODULE Linear2_Stream_CyclicStreamConcEx ------------------------
(*
 * Concurrent test: A (streaming producer) -> B (streaming consumer)
 * 
 * With concurrent EventLoop execution.
 * A yields streaming values, then returns.
 * B can start as soon as A yields (streaming consumption at level 1).
 * 
 * Expected behavior:
 *   1. B demanded, solver finds A (stale edge A->B)
 *   2. A starts running (EventLoop schedules it)
 *   3. A yields <<0,0>>
 *   4. B can now start (edge fresh at level 1), runs concurrently
 *   5. Interleaved execution of A and B yields
 *   6. Eventually both return
 *   7. Edge remains fresh at level 0 (mono complete)
 *)
EXTENDS CyclicConcurrentStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicConcurrentStreamingFlow.cfg

\* Simple linear graph: A -> B
SimpleEdges == {<<0, 1>>}

\* No cycles, so no break edges needed
SimpleBreakEdges == {}

\* Edge A->B has minRunLevel=1 (B is streaming consumer)
SimpleMinRunLevel == [e \in SimpleEdges |-> 1]

ConcreteNodes == {0, 1}
ConcreteEdges == SimpleEdges
ConcreteBreakEdges == SimpleBreakEdges
ConcreteMinRunLevel == SimpleMinRunLevel

=============================================================================
