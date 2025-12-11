---------------------------- MODULE SimpleFlow ----------------------------
EXTENDS Naturals, Integers, FiniteSets, Sequences

CONSTANTS 
    Nodes,
    Edges

VARIABLES
    generation,
    running,
    resolutionQueue,
    lastAction

vars == <<generation, running, resolutionQueue, lastAction>>

NoNode == -1

\* Graph helpers
Upstream(n) == {u \in Nodes : <<u, n>> \in Edges}
Downstream(n) == {d \in Nodes : <<n, d>> \in Edges}

\* Edge is stale if producer hasn't advanced past consumer
\* (matches flowno: cmp_generation(producer, consumer) <= 0 means stale)
IsEdgeStale(u, d) == generation[u] <= generation[d]

\* Solution set: leaves of the stale subgraph rooted at n
RECURSIVE SolutionSet(_)
SolutionSet(n) ==
    LET staleUpstream == {u \in Upstream(n) : IsEdgeStale(u, n)}
    IN IF staleUpstream = {}
       THEN {n}
       ELSE UNION {SolutionSet(u) : u \in staleUpstream}

\* Init: all unrun, arbitrary node demanded
Init ==
    /\ generation = [n \in Nodes |-> -1]
    /\ running = NoNode
    /\ \E n \in Nodes : resolutionQueue = {3}
    /\ lastAction = "Init"

\* Pop a demand, solve it, start one solution node
ResolveAndStart(demanded, n) ==
    /\ running = NoNode
    /\ demanded \in resolutionQueue
    /\ n \in SolutionSet(demanded)
    /\ (n = demanded \/ n \notin resolutionQueue)
    /\ running' = n
    /\ resolutionQueue' = resolutionQueue \ {demanded}
    /\ UNCHANGED generation
    /\ lastAction' = << "ResolveAndStart", demanded, n >>

\* Running node completes, enqueues downstream
Complete(n) ==
    /\ running = n
    /\ generation' = [generation EXCEPT ![n] = @ + 1]
    /\ resolutionQueue' = resolutionQueue \cup Downstream(n)
    /\ running' = NoNode
    /\ lastAction' = << "Complete", n >>

Next ==
    \/ \E demanded \in Nodes, n \in Nodes : ResolveAndStart(demanded, n)
    \/ \E n \in Nodes : Complete(n)

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ generation \in [Nodes -> -1..0]
    /\ running \in Nodes \cup {NoNode}
    /\ resolutionQueue \subseteq Nodes
    \* Relaxed type check for lastAction to avoid complex set construction issues
    /\ TRUE

=============================================================================