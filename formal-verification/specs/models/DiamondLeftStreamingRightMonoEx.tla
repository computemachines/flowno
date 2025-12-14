-------------------- MODULE DiamondLeftStreamingRightMonoEx --------------------
(*
 * Diamond graph: A -> B -> D (left branch, streaming edges)
 *                A -> C -> D (right branch, mono edges)
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
 *   B->D: minRunLevel=1 (streaming)
 *   A->C: minRunLevel=0 (mono)
 *   C->D: minRunLevel=0 (mono)
 * 
 * Expected behavior:
 *   - B can start when A yields (streaming consumption)
 *   - C waits for A to complete (mono consumption)
 *   - D needs both B and C inputs: B streaming, C mono
 *   - D can start when B yields and C completes
 *)
EXTENDS CyclicStreamingFlow

DiamondEdges == {<<0, 1>>, <<0, 2>>, <<1, 3>>, <<2, 3>>}
DiamondBreakEdges == {}

\* Left branch streaming (A->B, B->D), right branch mono (A->C, C->D)
DiamondMinRunLevel == [e \in DiamondEdges |-> 
    IF e = <<0, 1>> \/ e = <<1, 3>> THEN 1  \* Left branch: A->B, B->D streaming
    ELSE 0]  \* Right branch: A->C, C->D mono

=============================================================================
