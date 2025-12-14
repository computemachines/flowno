------------------------ MODULE CyclicConcurrentStreamingFlow ------------------------
(*
 * Concurrent streaming extension of CyclicStreamingFlow.
 * 
 * Combines:
 *   - Streaming generation model (tuples, ClipGen, StitchedGen, MinRunLevel)
 *   - EventLoopBasic task scheduling (Ready/Running/Sleeping)
 *   - Node streaming state (pc: wait0/wait1)
 *)
EXTENDS Naturals, Integers, FiniteSets, Sequences

CONSTANTS 
    Nodes,
    Edges,
    BreakEdges,
    MinRunLevel    \* [Edges -> {0, 1}]

\* Max node ID for EventLoopBasic binding
MaxNodeId == CHOOSE max \in Nodes : \A n \in Nodes : n <= max

\* EventLoopBasic variables (declared here, bound via INSTANCE)
VARIABLES
    taskState,
    joinWaiters

\* Flow-specific variables
VARIABLES
    generation,
    stitchCount,
    resolutionQueue,
    pc,              \* Node streaming state: "wait0" (ready for new gen) or "wait1" (mid-stream)
    lastAction

EL == INSTANCE EventLoopBasic WITH MaxTaskId <- MaxNodeId

vars == <<taskState, joinWaiters, generation, stitchCount, resolutionQueue, pc, lastAction>>
flowVars == <<generation, stitchCount, resolutionQueue, pc>>
elVars == <<taskState, joinWaiters>>

NoNode == -1

\* ===== Generation Representation =====
NeverRan == <<>>  \* Minimum generation (never run)

\* ===== Generation Comparison =====
CmpGen(g1, g2) ==
    IF g1 = g2 THEN 0
    ELSE IF g1 = <<>> THEN -1
    ELSE IF g2 = <<>> THEN 1
    ELSE IF Len(g1) > Len(g2) THEN
        LET prefix == SubSeq(g1, 1, Len(g2))
        IN IF prefix = g2 THEN -1
           ELSE IF Head(prefix) < Head(g2) THEN -1
           ELSE IF Head(prefix) > Head(g2) THEN 1
           ELSE IF Len(g2) >= 2 /\ prefix[2] < g2[2] THEN -1
           ELSE 1
    ELSE IF Len(g1) < Len(g2) THEN
        LET prefix == SubSeq(g2, 1, Len(g1))
        IN IF prefix = g1 THEN 1
           ELSE IF Head(g1) < Head(prefix) THEN -1
           ELSE IF Head(g1) > Head(prefix) THEN 1
           ELSE IF Len(g1) >= 2 /\ g1[2] < prefix[2] THEN -1
           ELSE 1
    ELSE
        IF Head(g1) < Head(g2) THEN -1
        ELSE IF Head(g1) > Head(g2) THEN 1
        ELSE IF Len(g1) = 1 THEN 0
        ELSE IF g1[2] < g2[2] THEN -1
        ELSE IF g1[2] > g2[2] THEN 1
        ELSE 0

\* ===== Clip Generation =====
ClipGen(gen, runLevel) ==
    IF gen = <<>> THEN <<>>
    ELSE IF runLevel = 1 THEN gen
    ELSE IF Len(gen) = 1 THEN gen
    ELSE IF gen[1] = 0 THEN <<>>
    ELSE <<gen[1] - 1>>

\* ===== Stitched Generation =====
StitchedGen(gen, stitch) ==
    IF gen = <<>> THEN
        IF stitch > 0 THEN <<stitch - 1>> ELSE <<>>
    ELSE IF Len(gen) = 1 THEN <<gen[1] + stitch>>
    ELSE <<gen[1] + stitch, gen[2]>>

\* ===== Increment Generation =====
IncrementGen(gen, runLevel) ==
    CASE gen = <<>> /\ runLevel = 0 -> <<0>>
      [] gen = <<>> /\ runLevel = 1 -> <<0, 0>>
      [] Len(gen) = 1 /\ runLevel = 0 -> <<gen[1] + 1>>
      [] Len(gen) = 1 /\ runLevel = 1 -> <<gen[1] + 1, 0>>
      [] Len(gen) = 2 /\ runLevel = 0 -> <<gen[1]>>
      [] Len(gen) = 2 /\ runLevel = 1 -> <<gen[1], gen[2] + 1>>

\* ===== Staleness =====
IsEdgeStale(u, d) ==
    LET edge == <<u, d>>
        runLevel == MinRunLevel[edge]
        clipped == ClipGen(generation[u], runLevel)
        stitched == StitchedGen(clipped, stitchCount[edge])
    IN CmpGen(stitched, generation[d]) <= 0

StaleSubgraph == {e \in Edges : IsEdgeStale(e[1], e[2])}

\* ===== Directed Reachability =====
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
    /\ taskState = [t \in EL!Tasks |-> [state |-> EL!Ready]]
    /\ joinWaiters = [t \in EL!Tasks |-> {}]
    /\ generation = [n \in Nodes |-> NeverRan]
    /\ stitchCount = [e \in Edges |-> 0]
    /\ resolutionQueue = {CHOOSE n \in Nodes : \A m \in Nodes : n <= m}
    /\ pc = [n \in Nodes |-> "wait0"]
    /\ lastAction = <<"Init">>

\* ===== Actions =====

\* Solver pops demand, finds solution, schedules a node
SolveAndSchedule(demanded, n) ==
    /\ demanded \in resolutionQueue
    /\ n \in SolutionNodes(demanded)
    /\ pc[n] \in {"wait0", "wait1"}
    /\ EL!Schedule(n)                              \* Precondition: IsReady(n), no one Running
    /\ resolutionQueue' = resolutionQueue \ {demanded}
    /\ stitchCount' = [e \in Edges |-> 
        IF e \in EdgesToStitch(demanded) 
        THEN stitchCount[e] + 1 
        ELSE stitchCount[e]]
    /\ UNCHANGED <<generation, pc>>
    /\ lastAction' = <<"SolveAndSchedule", demanded, n, pc[n]>>

\* Node yields streaming value
Yield(n) ==
    /\ EL!IsRunning(n)
    /\ EL!YieldReady(n)                            \* Running → Ready
    /\ generation' = [generation EXCEPT ![n] = IncrementGen(@, 1)]
    /\ pc' = [pc EXCEPT ![n] = "wait1"]
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ UNCHANGED stitchCount
    /\ lastAction' = <<"Yield", n, IncrementGen(generation[n], 1)>>

\* Node returns (completes generation)
Return(n) ==
    /\ EL!IsRunning(n)
    /\ EL!YieldReady(n)                            \* Running → Ready
    /\ generation' = [generation EXCEPT ![n] = IncrementGen(@, 0)]
    /\ pc' = [pc EXCEPT ![n] = "wait0"]
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ UNCHANGED stitchCount
    /\ lastAction' = <<"Return", n, IncrementGen(generation[n], 0)>>

\* Running node blocks (e.g., async sleep, barrier wait)
NodeSleep(n) ==
    /\ EL!YieldSleep(n)                            \* Running → Sleeping
    /\ UNCHANGED flowVars
    /\ lastAction' = <<"NodeSleep", n>>

\* Sleeping node wakes up
NodeWake(n) ==
    /\ EL!WakeFromSleep(n)                         \* Sleeping → Ready
    /\ UNCHANGED flowVars
    /\ lastAction' = <<"NodeWake", n>>

Next ==
    \/ \E demanded \in Nodes, n \in Nodes : SolveAndSchedule(demanded, n)
    \/ \E n \in Nodes : Yield(n)
    \/ \E n \in Nodes : Return(n)
    \/ \E n \in Nodes : NodeSleep(n)
    \/ \E n \in Nodes : NodeWake(n)

Spec == Init /\ [][Next]_vars

FairSpec == Spec /\ WF_vars(Next)

\* ===== State Constraint =====
MaxGen == 2
MaxStreamIdx == 3
StateConstraint == 
    \A n \in Nodes : 
        \/ generation[n] = <<>>
        \/ (Len(generation[n]) = 1 /\ generation[n][1] <= MaxGen)
        \/ (Len(generation[n]) = 2 /\ generation[n][1] <= MaxGen /\ generation[n][2] <= MaxStreamIdx)

\* ===== Type Invariant =====
ValidGeneration(g) ==
    \/ g = <<>>
    \/ (Len(g) = 1 /\ g[1] \in 0..100)
    \/ (Len(g) = 2 /\ g[1] \in 0..100 /\ g[2] \in 0..100)

TypeOK ==
    /\ EL!TypeOK
    /\ \A n \in Nodes : ValidGeneration(generation[n])
    /\ stitchCount \in [Edges -> 0..2]
    /\ resolutionQueue \subseteq Nodes
    /\ pc \in [Nodes -> {"wait0", "wait1"}]

\* ===== Safety Invariants =====

\* At most one task running (inherited from EventLoopBasic)
AtMostOneRunning == EL!AtMostOneRunning

\* Stitch count never exceeds 1
StitchAtMostOnce == \A e \in Edges : stitchCount[e] <= 1

\* pc=wait1 implies node has started streaming
PcConsistentWithGeneration ==
    \A n \in Nodes :
        pc[n] = "wait1" => (generation[n] # <<>> /\ Len(generation[n]) = 2)

\* If queue non-empty and no one running, we can make progress
ProgressPossible ==
    (resolutionQueue # {} /\ \A t \in Nodes : ~EL!IsRunning(t)) =>
    \E demanded \in resolutionQueue, n \in Nodes :
        /\ n \in SolutionNodes(demanded)
        /\ pc[n] \in {"wait0", "wait1"}
        /\ (EL!IsReady(n) \/ EL!IsSleeping(n))
        
=============================================================================