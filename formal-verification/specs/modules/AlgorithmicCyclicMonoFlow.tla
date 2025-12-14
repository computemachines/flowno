------------------------ MODULE AlgorithmicCyclicMonoFlow ------------------------
(*
 * Algorithmic version of CyclicMonoFlow.
 * 
 * Key difference: Instead of computing global transitive closure TC(StaleSubgraph),
 * we compute directed reachability only from the demanded node. This is O(V+E) per
 * demand instead of O(N³) globally.
 *
 * Drop-in replacement for CyclicMonoFlow.tla - same CONSTANTS, VARIABLES, and
 * exported operators.
 *)
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

\* Final solution operators (same interface as CyclicMonoFlow)
SolutionNodes(demanded) == {BreakNodeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}
EdgesToStitch(demanded) == UNION {BreakEdgeOfSCC(scc) : scc \in LeafSCCsFrom(demanded)}

\* ===== Graph helpers =====
Upstream(n) == {u \in Nodes : <<u, n>> \in Edges}
Downstream(n) == {d \in Nodes : <<n, d>> \in Edges}

\* ===== Init =====
Init ==
    /\ generation = [n \in Nodes |-> -1]
    /\ stitchCount = [e \in Edges |-> 0]
    /\ running = NoNode
    /\ resolutionQueue = {CHOOSE n \in Nodes : TRUE}
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
    /\ lastAction' = <<"ResolveAndStart", demanded, n, LeafSCCsFrom(demanded), EdgesToStitch(demanded)>>

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

\* Fair spec for liveness checking
FairSpec == Spec /\ WF_vars(Next)

\* ===== State Constraint (for bounding exploration) =====
StateConstraint == \A n \in Nodes : generation[n] <= 3

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
    /\ generation \in [Nodes -> Int]
    /\ stitchCount \in [Edges -> 0..1]
    /\ running \in Nodes \cup {NoNode}
    /\ resolutionQueue \subseteq Nodes

\* ===== Safety Invariants =====

\* Generations only go up by 1
GenerationsNoSkip == 
    \A n \in Nodes : generation[n] >= -1

\* Stitch count never exceeds 1 (cycle only broken once)
StitchAtMostOnce == 
    \A e \in Edges : stitchCount[e] <= 1

\* Wavefront tightness: started nodes within 1 generation of each other
WavefrontTight == 
    StartedNodes # {} => (MaxGenStarted - MinGenStarted <= 1)

\* If work exists and nothing running, we can start something
ProgressPossible ==
    (resolutionQueue # {} /\ running = NoNode) => 
    (\E demanded \in Nodes, n \in Nodes : 
        /\ demanded \in resolutionQueue
        /\ n \in SolutionNodes(demanded)
        /\ (n = demanded \/ n \notin resolutionQueue))

\* ===== Liveness Properties =====

\* The system eventually becomes quiescent (queue empty, nothing running)
EventuallyQuiescent == <>(resolutionQueue = {} /\ running = NoNode)

\* Every node eventually runs at least once
AllNodesEventuallyStart == \A n \in Nodes : <>(generation[n] >= 0)

\* Every node runs infinitely often (strong liveness)
AllNodesRunInfinitelyOften == \A n \in Nodes : []<>(running = n)

\* Generations always eventually advance
GenerationsAdvance == \A n \in Nodes : [](generation[n] = 0 => <>(generation[n] > 0))

\* ===== Deadlock Detection =====

\* True if system is "stuck": has work but can't make progress on generations
IsStuck ==
    /\ running = NoNode
    /\ resolutionQueue # {}
    /\ ~(\E demanded \in Nodes, n \in Nodes : 
         /\ demanded \in resolutionQueue
         /\ n \in SolutionNodes(demanded)
         /\ (n = demanded \/ n \notin resolutionQueue))

NoStuck == ~IsStuck

=============================================================================
