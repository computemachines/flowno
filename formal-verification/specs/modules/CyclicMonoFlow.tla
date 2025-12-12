---------------------------- MODULE CyclicMonoFlow ----------------------------
EXTENDS Naturals, Integers, FiniteSets

CONSTANTS 
    Nodes,
    Edges,
    BreakEdges

VARIABLES
    generation,
    stitchCount,
    running,
    resolutionQueue,
    lastAction

vars == <<generation, stitchCount, running, resolutionQueue, lastAction>>

NoNode == -1

\* ===== Staleness =====
IsEdgeStale(u, d) == 
    generation[u] + stitchCount[<<u, d>>] <= generation[d]

StaleSubgraph == {e \in Edges : IsEdgeStale(e[1], e[2])}

\* ===== Transitive Closure =====
RECURSIVE TC(_)
TC(R) ==
    LET R2 == R \cup {<<a, c>> \in Nodes \X Nodes : 
                      \E b \in Nodes : <<a, b>> \in R /\ <<b, c>> \in R}
    IN IF R2 = R THEN R ELSE TC(R2)

StaleReach == TC(StaleSubgraph)

\* ===== SCC Detection =====
InSameSCC(u, v) == 
    (u = v) \/ (<<u, v>> \in StaleReach /\ <<v, u>> \in StaleReach)

SCCOf(n) == {m \in Nodes : InSameSCC(n, m)}

\* Representative of each SCC (smallest node in the SCC)
SCCRep(n) == CHOOSE m \in SCCOf(n) : \A m2 \in SCCOf(n) : m <= m2

\* All distinct SCC representatives
AllSCCReps == {SCCRep(n) : n \in Nodes}

\* ===== SCC DAG =====
SCCEdge(rep1, rep2) == 
    rep1 # rep2 /\ 
    \E u \in SCCOf(rep1), v \in SCCOf(rep2) : <<u, v>> \in StaleSubgraph

IsLeafSCC(rep) == ~\E rep2 \in AllSCCReps : SCCEdge(rep2, rep)

\* ===== Upstream SCCs =====
SCCDagEdges == {<<r1, r2>> \in AllSCCReps \X AllSCCReps : SCCEdge(r1, r2)}
SCCDagReverse == {<<r2, r1>> : <<r1, r2>> \in SCCDagEdges}
SCCReachBackward == TC(SCCDagReverse)

UpstreamSCCReps(rep) == {rep} \cup {rep2 \in AllSCCReps : <<rep, rep2>> \in SCCReachBackward}

\* ===== Solution =====
SolutionSCCs(n) == {rep \in UpstreamSCCReps(SCCRep(n)) : IsLeafSCC(rep)}

IsCyclicSCC(rep) == 
    Cardinality(SCCOf(rep)) > 1 \/ \E e \in StaleSubgraph : e[1] \in SCCOf(rep) /\ e[2] \in SCCOf(rep)

BreakNodeOf(rep) ==
    IF ~IsCyclicSCC(rep)
    THEN CHOOSE n \in SCCOf(rep) : TRUE
    ELSE CHOOSE n \in SCCOf(rep) : \E e \in BreakEdges : e[2] = n /\ e[1] \in SCCOf(rep)

BreakEdgeOf(rep) ==
    IF ~IsCyclicSCC(rep)
    THEN {}
    ELSE {CHOOSE e \in BreakEdges : e[2] \in SCCOf(rep) /\ e[1] \in SCCOf(rep)}

SolutionNodes(demanded) == {BreakNodeOf(rep) : rep \in SolutionSCCs(demanded)}
EdgesToStitch(demanded) == UNION {BreakEdgeOf(rep) : rep \in SolutionSCCs(demanded)}

\* ===== Graph helpers =====
Upstream(n) == {u \in Nodes : <<u, n>> \in Edges}
Downstream(n) == {d \in Nodes : <<n, d>> \in Edges}

\* ===== Init =====
Init ==
    /\ generation = [n \in Nodes |-> -1]
    /\ stitchCount = [e \in Edges |-> 0]
    /\ running = NoNode
    /\ resolutionQueue = {CHOOSE n \in Nodes : TRUE}  \* arbitrary demand
    /\ lastAction = <<"Init">>

\* ===== Actions =====
ResolveAndStart(demanded, n) ==
    /\ running = NoNode
    /\ demanded \in resolutionQueue
    /\ n \in SolutionNodes(demanded)
    /\ (n = demanded \/ n \notin resolutionQueue)
    /\ running' = n
    /\ resolutionQueue' = resolutionQueue \ {demanded}
    /\ stitchCount' = [e \in Edges |-> 
        IF e \in EdgesToStitch(demanded) 
        THEN stitchCount[e] + 1 
        ELSE stitchCount[e]]
    /\ UNCHANGED generation
    /\ lastAction' = <<"ResolveAndStart", demanded, n, SolutionSCCs(demanded), EdgesToStitch(demanded)>>

Complete(n) ==
    /\ running = n
    /\ generation' = [generation EXCEPT ![n] = @ + 1]
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ running' = NoNode
    /\ UNCHANGED stitchCount
    /\ lastAction' = <<"Complete", n>>

Next ==
    \/ \E demanded \in Nodes, n \in Nodes : ResolveAndStart(demanded, n)
    \/ \E n \in Nodes : Complete(n)

Spec == Init /\ [][Next]_vars

\* ===== Debug Operators (for inspection) =====
DebugStaleSubgraph == StaleSubgraph
DebugStaleReach == StaleReach
DebugAllSCCReps == AllSCCReps

\* ===== Invariants =====
TypeOK ==
    /\ generation \in [Nodes -> -1..2]
    /\ stitchCount \in [Edges -> 0..1]
    /\ running \in Nodes \cup {NoNode}
    /\ resolutionQueue \subseteq Nodes
    
\* A "bad" state: work exists but no node can actually complete
SemanticDeadlock ==
    /\ resolutionQueue # {} \/ running # NoNode  \* work exists
    /\ ~ENABLED (\E n \in Nodes : Complete(n))   \* but Complete is disabled

\* Invariant: we're never in semantic deadlock
NoSemanticDeadlock == ~SemanticDeadlock
=============================================================================
