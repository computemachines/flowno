-------------------- MODULE CyclicTriangleAllStreamingEx --------------------
(*
 * Cyclic triangle: A -> B -> C -> A (all edges streaming)
 * 
 * Triangle topology:
 *     A(0) ---> B(1)
 *      ^         |
 *      |         v
 *     C(2) <-----+
 * 
 * Edge configuration:
 *   A->B: minRunLevel=1 (streaming)
 *   B->C: minRunLevel=1 (streaming)
 *   C->A: minRunLevel=1 (streaming) - BREAK EDGE
 * 
 * All edges are streaming, break edge on C->A.
 * 
 * Expected behavior:
 *   - A demanded, finds stale C->A edge (break edge), demand C
 *   - C demanded, finds stale B->C edge, demand B
 *   - B demanded, finds stale A->B edge, demand A
 *   - A can start (break edge allows it)
 *   - A yields, B can start (streaming consumption)
 *   - B yields, C can start (streaming consumption)
 *   - C yields, A can continue next generation (streaming consumption)
 *   - Maximum concurrency: all nodes can run with streaming interleaving
 *)
EXTENDS CyclicStreamingFlow

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<2, 0>>}  \* Break on C->A edge

\* All edges are streaming
TriangleMinRunLevel == [e \in TriangleEdges |-> 1]

=============================================================================
