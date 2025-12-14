------------------------ MODULE CyclicConcurrentMonoFlow ------------------------
EXTENDS Naturals, Integers, FiniteSets

CONSTANTS 
    Nodes,
    Edges,
    BreakEdges

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
    lastAction

EL == INSTANCE EventLoopBasic WITH MaxTaskId <- MaxNodeId

vars == <<taskState, joinWaiters, generation, stitchCount, resolutionQueue, lastAction>>
flowVars == <<generation, stitchCount, resolutionQueue>>
elVars == <<taskState, joinWaiters>>

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

\* Unrolled TC for performance (iterate a fixed number of times)
\* TC(R) ==
\*     LET Compose(S) == S \cup {<<a, c>> \in Nodes \X Nodes : 
\*                               \E b \in Nodes : <<a, b>> \in S /\ <<b, c>> \in S}
\*     IN Compose(Compose(Compose(Compose(R))))

StaleReach == TC(StaleSubgraph)

\* ===== SCC Detection =====
InSameSCC(u, v) == 
    (u = v) \/ (<<u, v>> \in StaleReach /\ <<v, u>> \in StaleReach)

SCCOf(n) == {m \in Nodes : InSameSCC(n, m)}

SCCRep(n) == CHOOSE m \in SCCOf(n) : \A m2 \in SCCOf(n) : m <= m2

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
    Cardinality(SCCOf(rep)) > 1 \/ 
    \E e \in StaleSubgraph : e[1] \in SCCOf(rep) /\ e[2] \in SCCOf(rep)

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
    /\ taskState = [t \in EL!Tasks |-> [state |-> EL!Ready]]
    /\ joinWaiters = [t \in EL!Tasks |-> {}]
    /\ generation = [n \in Nodes |-> -1]
    /\ stitchCount = [e \in Edges |-> 0]
    /\ resolutionQueue = {CHOOSE n \in Nodes : TRUE}
    /\ lastAction = <<"Init">>

\* ===== Actions =====

\* Pop demand from queue, solve to find root causes, schedule one solution node
ResolveAndSchedule(demanded, n) ==
    /\ demanded \in resolutionQueue
    /\ n \in SolutionNodes(demanded)
    /\ (n = demanded \/ n \notin resolutionQueue)
    /\ EL!Schedule(n)                              \* Precondition: IsReady(n), no one Running
    /\ resolutionQueue' = resolutionQueue \ {demanded}
    /\ stitchCount' = [e \in Edges |-> 
        IF e \in EdgesToStitch(demanded) 
        THEN stitchCount[e] + 1 
        ELSE stitchCount[e]]
    /\ UNCHANGED generation
    /\ lastAction' = <<"ResolveAndSchedule", demanded, n, EdgesToStitch(demanded)>>

\* Running node completes its work, goes back to Ready
NodeComplete(n) ==
    /\ EL!IsRunning(n)
    /\ EL!YieldReady(n)                            \* Running → Ready
    /\ generation' = [generation EXCEPT ![n] = @ + 1]
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ UNCHANGED stitchCount
    /\ lastAction' = <<"NodeComplete", n>>

\* Running node blocks (e.g., waiting on input, barrier)
NodeSleep(n) ==
    /\ EL!YieldSleep(n)                            \* Running → Sleeping
    /\ UNCHANGED flowVars
    /\ lastAction' = <<"NodeSleep", n>>

\* Sleeping node wakes up (e.g., input available, barrier cleared)
NodeWake(n) ==
    /\ EL!WakeFromSleep(n)                         \* Sleeping → Ready
    /\ UNCHANGED flowVars
    /\ lastAction' = <<"NodeWake", n>>

Next ==
    \/ \E demanded \in Nodes, n \in Nodes : ResolveAndSchedule(demanded, n)
    \/ \E n \in Nodes : NodeComplete(n)
    \/ \E n \in Nodes : NodeSleep(n)
    \/ \E n \in Nodes : NodeWake(n)

Spec == Init /\ [][Next]_vars

FairSpec == Spec /\ WF_vars(Next)

\* ===== State Constraint =====
StateConstraint == \A n \in Nodes : generation[n] <= 2

\* ===== Helper Operators =====
StartedNodes == {n \in Nodes : generation[n] >= 0}

MaxGenStarted == 
    IF StartedNodes = {} THEN -1
    ELSE CHOOSE g \in {generation[n] : n \in StartedNodes} : 
         \A n \in StartedNodes : generation[n] <= g

MinGenStarted == 
    IF StartedNodes = {} THEN -1
    ELSE CHOOSE g \in {generation[n] : n \in StartedNodes} : 
         \A n \in StartedNodes : generation[n] >= g

\* ===== Type Invariant =====
TypeOK ==
    /\ EL!TypeOK
    /\ generation \in [Nodes -> -1..10]
    /\ stitchCount \in [Edges -> 0..1]
    /\ resolutionQueue \subseteq Nodes

\* ===== Safety Invariants =====

\* At most one task running (inherited from EventLoopBasic)
AtMostOneRunning == EL!AtMostOneRunning

\* Stitch count never exceeds 1
StitchAtMostOnce == \A e \in Edges : stitchCount[e] <= 1

\* Wavefront tightness
WavefrontTight == 
    StartedNodes # {} => (MaxGenStarted - MinGenStarted <= 1)

\* If work exists and nothing running, we can start something
ProgressPossible ==
    (resolutionQueue # {} /\ \A t \in Nodes : ~EL!IsRunning(t)) => 
    (\E demanded \in Nodes, n \in Nodes : 
        /\ demanded \in resolutionQueue
        /\ n \in SolutionNodes(demanded)
        /\ (n = demanded \/ n \notin resolutionQueue)
        /\ (EL!IsReady(n) \/ EL!IsSleeping(n)))  \* Sleeping = will wake eventually

\* ===== Liveness Properties =====

\* Every node eventually runs at least once
AllNodesEventuallyStart == \A n \in Nodes : <>(generation[n] >= 0)

\* Generations always eventually advance
GenerationsAdvance == 
    \A n \in Nodes : [](generation[n] >= 0 => <>(generation[n] > 0))

=============================================================================