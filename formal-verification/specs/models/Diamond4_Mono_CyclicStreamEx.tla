-------------------- MODULE Diamond4_Mono_CyclicStreamEx --------------------
(*
 * Diamond graph with all edges mono (baseline case).
 * 
 * Diamond topology:
 *     A(0)
 *    /    \
 *   B(1)  C(2)
 *    \    /
 *     D(3)
 * 
 * Edge configuration:
 *   A->B: minRunLevel=0 (mono)
 *   A->C: minRunLevel=0 (mono)
 *   B->D: minRunLevel=0 (mono)
 *   C->D: minRunLevel=0 (mono)
 * 
 * Expected behavior:
 *   - B waits for A to complete (mono consumption)
 *   - C waits for A to complete (mono consumption)
 *   - D waits for both B and C to complete (mono consumption)
 *   - Sequential execution pattern with some parallelism (B and C can run concurrently)
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}
DiamondBreakEdges == {}

\* All edges are mono
DiamondMinRunLevel == [e \in DiamondEdges |-> 0]

ConcreteNodes == {0, 1, 2, 3}
ConcreteEdges == DiamondEdges
ConcreteBreakEdges == DiamondBreakEdges
ConcreteMinRunLevel == DiamondMinRunLevel

=============================================================================
