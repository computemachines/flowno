-------------------- MODULE DiamondTopStreamingRestMonoEx --------------------
(*
 * Diamond graph with top edge streaming, rest mono.
 * 
 * Diamond topology:
 *     A(0)
 *    /    \
 *   B(1)  C(2)
 *    \    /
 *     D(3)
 * 
 * Edge configuration:
 *   A->B: minRunLevel=1 (streaming) - TOP EDGE
 *   A->C: minRunLevel=0 (mono)
 *   B->D: minRunLevel=0 (mono)
 *   C->D: minRunLevel=0 (mono)
 * 
 * Expected behavior:
 *   - B can start when A yields (streaming consumption on top edge)
 *   - C waits for A to complete (mono consumption)
 *   - D waits for both B and C to complete (both mono consumption)
 *)
EXTENDS CyclicStreamingFlow

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}
DiamondBreakEdges == {}

\* Only A->B is streaming, rest are mono
DiamondMinRunLevel == [e \in DiamondEdges |-> 
    IF e = <<0, 1>> THEN 1  \* A->B streaming (top edge)
    ELSE 0]  \* All other edges mono

=============================================================================
