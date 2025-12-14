-------------------- MODULE DiamondAllStreamingEx --------------------
(*
 * Diamond graph with all edges streaming.
 * 
 * Diamond topology:
 *     A(0)
 *    /    \
 *   B(1)  C(2)
 *    \    /
 *     D(3)
 * 
 * Edge configuration:
 *   A->B: minRunLevel=1 (streaming)
 *   A->C: minRunLevel=1 (streaming)
 *   B->D: minRunLevel=1 (streaming)
 *   C->D: minRunLevel=1 (streaming)
 * 
 * Expected behavior:
 *   - B can start when A yields (streaming consumption)
 *   - C can start when A yields (streaming consumption)
 *   - D can start when both B and C yield (streaming consumption)
 *   - Maximum concurrency: all nodes can run with streaming interleaving
 *)
EXTENDS CyclicStreamingFlow

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}
DiamondBreakEdges == {}

\* All edges are streaming
DiamondMinRunLevel == [e \in DiamondEdges |-> 1]

=============================================================================
