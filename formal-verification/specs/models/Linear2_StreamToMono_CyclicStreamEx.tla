-------------------- MODULE Linear2_StreamToMono_CyclicStreamEx --------------------
(*
 * Simple test: A (streaming producer) -> B (mono consumer)
 * 
 * A yields streaming values, then returns.
 * B waits for A's mono output (run level 0), then runs.
 * 
 * Expected behavior:
 *   1. B demanded, solver finds A (stale edge A->B)
 *   2. A yields <<0,0>>, <<0,1>>, ... (B still can't start - edge stale at level 0)
 *   3. A returns <<0>> (mono complete)
 *   4. B can now start (edge fresh at level 0)
 *   5. B returns <<0>>
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

\* Simple linear graph: A -> B
SimpleEdges == {<<0, 1>>}

\* No cycles, so no break edges needed
SimpleBreakEdges == {}

\* Edge A->B has minRunLevel=0 (B is mono consumer)
SimpleMinRunLevel == [e \in SimpleEdges |-> 0]

ConcreteNodes == {0, 1}
ConcreteEdges == SimpleEdges
ConcreteBreakEdges == SimpleBreakEdges
ConcreteMinRunLevel == SimpleMinRunLevel

=============================================================================
