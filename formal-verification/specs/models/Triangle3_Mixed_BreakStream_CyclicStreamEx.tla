-------------------- MODULE Triangle3_Mixed_BreakStream_CyclicStreamEx --------------------
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
 *   A->B: minRunLevel=0 (mono)
 *   B->C: minRunLevel=1 (streaming) - BREAK EDGE
 *   C->A: minRunLevel=1 (streaming)
 * 
 * Break edge on a streaming edge (B->C).
 * 
 * Expected behavior:
 *   - A demanded, finds stale C->A edge, demand C
 *   - C demanded, finds stale B->C edge (break edge), demand B
 *   - B demanded, finds stale A->B edge, demand A
 *   - A can start (eventually via break edge resolution)
 *   - A completes, B can start (mono consumption)
 *   - B yields, C can start (streaming consumption, break edge allows)
 *   - C yields, A can continue next generation (streaming consumption)
 *   - Cycle continues with mixed mono/streaming
 *)
EXTENDS CyclicStreamingFlow

\* Use config: formal-verification/specs/model-tests/CyclicStreamingFlow.cfg

TriangleEdges == {<<0, 1>>, <<1, 2>>, <<2, 0>>}
TriangleBreakEdges == {<<1, 2>>}  \* Break on streaming edge

\* Two streaming edges, one mono
TriangleMinRunLevel == [e \in TriangleEdges |-> 
    IF e = <<0, 1>> THEN 0  \* A->B mono
    ELSE 1]  \* B->C and C->A streaming (break edge B->C is streaming)

ConcreteNodes == {0, 1, 2}
ConcreteEdges == TriangleEdges
ConcreteBreakEdges == TriangleBreakEdges
ConcreteMinRunLevel == TriangleMinRunLevel

=============================================================================
