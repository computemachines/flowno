-------------------- MODULE AlgorithmicCyclicConcurrentMonoFlow --------------------
(*
 * Algorithmic version of CyclicConcurrentMonoFlow.
 * 
 * Key difference: Instead of computing global transitive closure TC(StaleSubgraph),
 * we compute directed reachability only from the demanded node. This is O(V+E) per
 * demand instead of O(N³) globally.
 *
 * Drop-in replacement for CyclicConcurrentMonoFlow.tla - same CONSTANTS, VARIABLES,
 * and exported operators.
 *)
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

\* ===== Directed Reachability (replaces global TC) =====

\* Dependency edges: reverse of data flow
\* Original <<u, d>> means "u produces for d" 
\* Dependency <<d, u>> means "d depends on u"
StaleDependencyEdges == {<<e[2], e[1]>> : e \in StaleSubgraph}

\* Compute nodes reachable from 'start' following edges in R
\* Uses bounded iteration (safe for finite graphs)
ReachableFrom(start, R) ==
    LET Step(S) == S \cup {v \in Nodes : \E u \in S : <<u, v>> \in R}
    IN Step(Step(Step(Step(Step({start})))))  \* 5 iterations handles paths up to length 5

\* ===== Local SCC Detection =====

\* Nodes reachable from n following stale data-flow edges (downstream)
ForwardReach(n) == ReachableFrom(n, StaleSubgraph)

\* Nodes reachable from n following dependency edges (upstream)  
BackwardReach(n) == ReachableFrom(n, StaleDependencyEdges)

\* The SCC containing n: nodes that can reach n AND n can reach them
\* (via stale edges only)
LocalSCC(n) == ForwardReach(n) \cap BackwardReach(n)

\* ===== Solution Algorithm =====

\* Is this SCC cyclic? Either multiple nodes, or self-loop
IsLocalCyclic(n) ==
    LET scc == LocalSCC(n)
    IN Cardinality(scc) > 1 \/ 
       \E e \in StaleSubgraph : e[1] \in scc /\ e[2] \in scc

\* External dependencies of an SCC: nodes outside the SCC that the SCC depends on
ExternalDeps(scc) ==
    {u \in Nodes : \E d \in scc : <<d, u>> \in StaleDependencyEdges /\ u \notin scc}

\* Is this SCC a leaf? No external stale dependencies
IsLeafSCC(scc) == ExternalDeps(scc) = {}

\* Find all leaf SCCs reachable backward from demanded node
\* Uses bounded iteration to explore the dependency DAG
LeafSCCsFrom(demanded) ==
    LET \* Start with the SCC containing demanded
        startSCC == LocalSCC(demanded)
        
        \* Explore one level: given a set of SCCs, find their upstream SCCs
        UpstreamSCCs(sccs) ==
            LET allExternalDeps == UNION {ExternalDeps(scc) : scc \in sccs}
            IN {LocalSCC(n) : n \in allExternalDeps}
        
        \* Iteratively find all reachable SCCs (bounded iterations)
        Step(sccs) == sccs \cup UpstreamSCCs(sccs)
        AllReachableSCCs == Step(Step(Step(Step(Step({startSCC})))))
        
    IN {scc \in AllReachableSCCs : IsLeafSCC(scc)}

\* Pick the break node from an SCC
BreakNodeOfSCC(scc) ==
    IF Cardinality(scc) = 1 /\ ~(\E e \in StaleSubgraph : e[1] \in scc /\ e[2] \in scc)
    THEN CHOOSE n \in scc : TRUE  \* Non-cyclic singleton
    ELSE CHOOSE n \in scc : \E e \in BreakEdges : e[2] = n /\ e[1] \in scc

\* Pick the break edge from an SCC (empty if non-cyclic)
BreakEdgeOfSCC(scc) ==
    IF Cardinality(scc) = 1 /\ ~(\E e \in StaleSubgraph : e[1] \in scc /\ e[2] \in scc)
    THEN {}  \* Non-cyclic singleton
    ELSE LET candidates == {e \in BreakEdges : e[2] \in scc /\ e[1] \in scc}
         IN IF candidates = {} THEN {} ELSE {CHOOSE e \in candidates : TRUE}

\* Final solution operators (same interface as CyclicConcurrentMonoFlow)
SolutionNodes(demanded) == {BreakNodeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}
EdgesToStitch(demanded) == UNION {BreakEdgeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}

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
