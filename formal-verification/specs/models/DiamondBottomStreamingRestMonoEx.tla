-------------------- MODULE DiamondBottomStreamingRestMonoEx --------------------
(*
 * Diamond graph with bottom edge streaming, rest mono.
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
 *   B->D: minRunLevel=1 (streaming) - BOTTOM EDGE
 *   C->D: minRunLevel=0 (mono)
 * 
 * Expected behavior:
 *   - B waits for A to complete (mono consumption)
 *   - C waits for A to complete (mono consumption)
 *   - D can start when B yields and C completes
 *   - D consumes B's output in streaming fashion, C's output as mono
 *)
EXTENDS CyclicStreamingFlow

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}
DiamondBreakEdges == {}

\* Only B->D is streaming, rest are mono
DiamondMinRunLevel == [e \in DiamondEdges |-> 
    IF e = <<1, 3>> THEN 1  \* B->D streaming (bottom edge)
    ELSE 0]  \* All other edges mono

=============================================================================
