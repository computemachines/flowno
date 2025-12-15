-------------------- MODULE Triangle3_Mixed_BreakMono_CyclicStreamEx --------------------
(*
 * Cyclic triangle: A -> B -> C -> A
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
 *   C->A: minRunLevel=0 (mono) - BREAK EDGE
 * 
 * Break edge on the mono edge (C->A).
 * 
 * Expected behavior:
 *   - A demanded, finds stale C->A edge, demand C
 *   - C demanded, finds stale B->C edge, demand B
 *   - B demanded, finds stale A->B edge, demand A
 *   - A can start (break edge allows it)
 *   - A yields, B can start (streaming consumption)
 *   - B yields, C can start (streaming consumption)
 *   - C completes, A can continue (mono consumption, break edge fresh)
 *   - Cycle continues with streaming interleaving
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<2, 0>>}  \* Break on mono edge

\* Two streaming edges, one mono (the break edge)
TriangleMinRunLevel == [e \in TriangleEdges |-> 
    IF e = <<2, 0>> THEN 0  \* C->A mono (break edge)
    ELSE 1]  \* A->B and B->C streaming

ConcreteNodes == {0, 1, 2}
ConcreteEdges == TriangleEdges
ConcreteBreakEdges == TriangleBreakEdges
ConcreteMinRunLevel == TriangleMinRunLevel

=============================================================================
