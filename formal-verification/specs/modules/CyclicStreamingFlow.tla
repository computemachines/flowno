---------------------------- MODULE CyclicStreamingFlow ----------------------------
(*
 * Streaming extension of CyclicMonoFlow.
 * 
 * Key changes from mono:
 *   - Generation is a tuple (sequence) instead of integer
 *   - Each edge has MinRunLevel attribute (0=mono, 1=streaming)
 *   - Nodes can Yield (streaming) or Return (complete)
 *   - pc tracks node position: wait0 (ready for new gen) vs wait1 (mid-stream)
 *)
EXTENDS Naturals, Integers, FiniteSets, Sequences

CONSTANTS 
    Nodes,
    Edges,
    BreakEdges,
    MinRunLevel    \* [Edges -> {0, 1}]

VARIABLES
    generation,        \* [Nodes -> Generation]  where Generation = None | <<a>> | <<a,i>>
    stitchCount,       \* [Edges -> Nat]
    resolutionQueue,   \* SUBSET Nodes
    pc,                \* [Nodes -> {"wait0", "wait1"}]
    activeNode,        \* Nodes \cup {NoNode}
    lastAction

vars == <<generation, stitchCount, resolutionQueue, pc, activeNode, lastAction>>

NoNode == -1

\* ===== Generation Representation =====
\* We use sequences (tuples) for generation:
\*   <<>> = uninitialized/never run (minimum)  
\*   <<a, i>> = streaming index i within generation a
\*   <<a>> = completed generation a (mono)
\*   Note: In code, None is minimum and <<>> is maximum. Here we use <<>> as minimum
\*   for simplicity since TLA+ sequences are easier to work with.

NeverRan == <<>>  \* Minimum generation (never run)

\* ===== Generation Comparison =====
\* Ordering: <<>> < <<0,0>> < <<0,1>> < <<0>> < <<1,0>> < <<1>> < ...
\* Rule: Compare element-by-element. If equal up to shorter length, shorter is GREATER.

CmpGen(g1, g2) ==
    IF g1 = g2 THEN 0
    ELSE IF g1 = <<>> THEN -1           \* <<>> is minimum
    ELSE IF g2 = <<>> THEN 1
    ELSE IF Len(g1) > Len(g2) THEN      \* Longer tuple = older = smaller
        LET prefix == SubSeq(g1, 1, Len(g2))
        IN IF prefix = g2 THEN -1       \* g1 is longer, prefixes equal -> g1 < g2
           ELSE IF Head(prefix) < Head(g2) THEN -1
           ELSE IF Head(prefix) > Head(g2) THEN 1
           ELSE IF Len(g2) >= 2 /\ prefix[2] < g2[2] THEN -1
           ELSE 1
    ELSE IF Len(g1) < Len(g2) THEN      \* Shorter tuple = newer = greater
        LET prefix == SubSeq(g2, 1, Len(g1))
        IN IF prefix = g1 THEN 1        \* g2 is longer, prefixes equal -> g1 > g2
           ELSE IF Head(g1) < Head(prefix) THEN -1
           ELSE IF Head(g1) > Head(prefix) THEN 1
           ELSE IF Len(g1) >= 2 /\ g1[2] < prefix[2] THEN -1
           ELSE 1
    ELSE                                 \* Same length
        IF Head(g1) < Head(g2) THEN -1
        ELSE IF Head(g1) > Head(g2) THEN 1
        ELSE IF Len(g1) = 1 THEN 0       \* Both <<a>>, equal
        ELSE IF g1[2] < g2[2] THEN -1    \* Both <<a,i>>, compare second element
        ELSE IF g1[2] > g2[2] THEN 1
        ELSE 0

\* ===== Clip Generation =====
\* Clip to maximum length of runLevel + 1
\* runLevel=0: return highest mono gen <= gen (length 1)
\* runLevel=1: return gen as-is (length up to 2)
ClipGen(gen, runLevel) ==
    IF gen = <<>> THEN <<>>
    ELSE IF runLevel = 1 THEN gen        \* Keep full tuple for streaming
    ELSE IF Len(gen) = 1 THEN gen        \* Already mono length
    ELSE IF gen[1] = 0 THEN <<>>         \* <<0, i>> clips to <<>> at level 0
    ELSE <<gen[1] - 1>>                  \* <<a, i>> clips to <<a-1>> at level 0

\* ===== Stitched Generation =====
\* Add stitch to first element
StitchedGen(gen, stitch) ==
    IF gen = <<>> THEN
        IF stitch > 0 THEN <<stitch - 1>> ELSE <<>>
    ELSE IF Len(gen) = 1 THEN <<gen[1] + stitch>>
    ELSE <<gen[1] + stitch, gen[2]>>

\* ===== Increment Generation =====
\* runLevel=0: Return (complete generation)
\* runLevel=1: Yield (streaming value)
IncrementGen(gen, runLevel) ==
    CASE gen = <<>> /\ runLevel = 0 -> <<0>>           \* First return
      [] gen = <<>> /\ runLevel = 1 -> <<0, 0>>        \* First yield
      [] Len(gen) = 1 /\ runLevel = 0 -> <<gen[1] + 1>> \* Mono -> next mono
      [] Len(gen) = 1 /\ runLevel = 1 -> <<gen[1] + 1, 0>> \* Mono -> start streaming
      [] Len(gen) = 2 /\ runLevel = 0 -> <<gen[1]>>    \* Streaming -> complete
      [] Len(gen) = 2 /\ runLevel = 1 -> <<gen[1], gen[2] + 1>> \* Continue streaming

\* ===== Staleness =====
IsEdgeStale(u, d) ==
    LET edge == <<u, d>>
        runLevel == MinRunLevel[edge]
        clipped == ClipGen(generation[u], runLevel)
        stitched == StitchedGen(clipped, stitchCount[edge])
    IN CmpGen(stitched, generation[d]) <= 0

StaleSubgraph == {e \in Edges : IsEdgeStale(e[1], e[2])}

\* ===== Directed Reachability (from AlgorithmicCyclicMonoFlow) =====
StaleDependencyEdges == {<<e[2], e[1]>> : e \in StaleSubgraph}

ReachableFrom(start, R) ==
    LET Step(S) == S \cup {v \in Nodes : \E u \in S : <<u, v>> \in R}
    IN Step(Step(Step(Step(Step({start})))))

ForwardReach(n) == ReachableFrom(n, StaleSubgraph)
BackwardReach(n) == ReachableFrom(n, StaleDependencyEdges)
LocalSCC(n) == ForwardReach(n) \cap BackwardReach(n)

ExternalDeps(scc) ==
    {u \in Nodes : \E d \in scc : <<d, u>> \in StaleDependencyEdges /\ u \notin scc}

IsLeafSCC(scc) == ExternalDeps(scc) = {}

LeafSCCsFrom(demanded) ==
    LET startSCC == LocalSCC(demanded)
        UpstreamSCCs(sccs) ==
            LET allExternalDeps == UNION {ExternalDeps(scc) : scc \in sccs}
            IN {LocalSCC(n) : n \in allExternalDeps}
        Step(sccs) == sccs \cup UpstreamSCCs(sccs)
        AllReachableSCCs == Step(Step(Step(Step(Step({startSCC})))))
    IN {scc \in AllReachableSCCs : IsLeafSCC(scc)}

IsLocalCyclic(scc) ==
    Cardinality(scc) > 1 \/ 
    \E e \in StaleSubgraph : e[1] \in scc /\ e[2] \in scc

BreakNodeOfSCC(scc) ==
    IF ~IsLocalCyclic(scc)
    THEN CHOOSE n \in scc : TRUE
    ELSE CHOOSE n \in scc : \E e \in BreakEdges : e[2] = n /\ e[1] \in scc

BreakEdgeOfSCC(scc) ==
    IF ~IsLocalCyclic(scc)
    THEN {}
    ELSE LET candidates == {e \in BreakEdges : e[2] \in scc /\ e[1] \in scc}
         IN IF candidates = {} THEN {} ELSE {CHOOSE e \in candidates : TRUE}

SolutionNodes(demanded) == {BreakNodeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}
EdgesToStitch(demanded) == UNION {BreakEdgeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}

\* ===== Graph Helpers =====
Downstream(n) == {d \in Nodes : <<n, d>> \in Edges}

\* ===== Initial State =====
Init ==
    /\ generation = [n \in Nodes |-> NeverRan]
    /\ stitchCount = [e \in Edges |-> 0]
    /\ resolutionQueue = {CHOOSE n \in Nodes : \A m \in Nodes : n <= m}  \* Pick smallest node
    /\ pc = [n \in Nodes |-> "wait0"]
    /\ activeNode = NoNode
    /\ lastAction = <<"Init">>

\* ===== Actions =====

\* Solver pops demand, finds solution, resumes a node
SolveAndResume(demanded, n) ==
    /\ demanded \in resolutionQueue
    /\ n \in SolutionNodes(demanded)
    /\ pc[n] \in {"wait0", "wait1"}         \* Can resume from either wait state
    /\ activeNode = NoNode                   \* No one else executing
    /\ activeNode' = n
    /\ resolutionQueue' = resolutionQueue \ {demanded}
    /\ stitchCount' = [e \in Edges |-> 
        IF e \in EdgesToStitch(demanded) 
        THEN stitchCount[e] + 1 
        ELSE stitchCount[e]]
    /\ UNCHANGED <<generation, pc>>
    /\ lastAction' = <<"SolveAndResume", demanded, n, pc[n], SolutionNodes(demanded)>>

\* Node yields streaming value
Yield(n) ==
    /\ activeNode = n
    /\ generation' = [generation EXCEPT ![n] = IncrementGen(@, 1)]
    /\ pc' = [pc EXCEPT ![n] = "wait1"]
    /\ activeNode' = NoNode
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ UNCHANGED stitchCount
    /\ lastAction' = <<"Yield", n, IncrementGen(generation[n], 1)>>

\* Node returns (completes generation)
Return(n) ==
    /\ activeNode = n
    /\ generation' = [generation EXCEPT ![n] = IncrementGen(@, 0)]
    /\ pc' = [pc EXCEPT ![n] = "wait0"]
    /\ activeNode' = NoNode
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ UNCHANGED stitchCount
    /\ lastAction' = <<"Return", n, IncrementGen(generation[n], 0)>>

Next ==
    \/ \E demanded \in Nodes, n \in Nodes : SolveAndResume(demanded, n)
    \/ \E n \in Nodes : Yield(n)
    \/ \E n \in Nodes : Return(n)

Spec == Init /\ [][Next]_vars

FairSpec == Spec /\ WF_vars(Next)

\* ===== State Constraint =====
MaxGen == 2
StateConstraint == 
    \A n \in Nodes : 
        \/ generation[n] = <<>>
        \/ (Len(generation[n]) >= 1 /\ generation[n][1] <= MaxGen)

\* ===== Type Invariant =====
ValidGeneration(g) ==
    \/ g = <<>>
    \/ (Len(g) = 1 /\ g[1] \in Nat)
    \/ (Len(g) = 2 /\ g[1] \in Nat /\ g[2] \in Nat)

TypeOK ==
    /\ \A n \in Nodes : ValidGeneration(generation[n])
    /\ stitchCount \in [Edges -> 0..2]
    /\ resolutionQueue \subseteq Nodes
    /\ pc \in [Nodes -> {"wait0", "wait1"}]
    /\ activeNode \in Nodes \cup {NoNode}

\* ===== Safety Invariants =====

AtMostOneActive == 
    Cardinality({n \in Nodes : activeNode = n}) <= 1

StitchAtMostOnce == 
    \A e \in Edges : stitchCount[e] <= 1

\* pc=wait1 implies node has started streaming (generation has length 2)
PcConsistentWithGeneration ==
    \A n \in Nodes :
        pc[n] = "wait1" => (generation[n] # <<>> /\ Len(generation[n]) = 2)

\* If queue non-empty and no one active, we can make progress
ProgressPossible ==
    (resolutionQueue # {} /\ activeNode = NoNode) =>
    \E demanded \in resolutionQueue, n \in Nodes :
        /\ n \in SolutionNodes(demanded)
        /\ pc[n] \in {"wait0", "wait1"}

=============================================================================
