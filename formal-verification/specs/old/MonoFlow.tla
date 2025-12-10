---------------------------- MODULE MonoFlow ------------------------------
(*
 * MonoFlow: Dataflow graph execution without streaming.
 * 
 * This spec models a simplified version of Flowno's dataflow execution:
 *   - Nodes are pure (async) functions that read inputs and produce outputs
 *   - Nodes run to completion (no partial results, no stalling on nonready inputs, only on async ops)
 *   - Generations track which output version is current
 *   - Resolution determines which nodes to evaluate when outputs are stale
 * 
 * Key concepts:
 *   - Generation: A tuple that increments each time a node evaluates
 *   - Stale: A node is stale if any upstream has a newer generation
 *   - Resolution: Finding "root cause" nodes to evaluate (leaf SCCs of stale graph)
 *)
EXTENDS Naturals, FiniteSets, Sequences, Integers

(* ===== CONSTANTS ===== *)

CONSTANTS
    Nodes,           \* Set of node IDs
    MaxGeneration,   \* Maximum generation number for model checking bounds
    Edges            \* Set of <<upstream, downstream>> pairs

(* ===== GRAPH OPERATIONS ===== *)

(*
 * Upstream(n): Nodes that feed into n (n reads their outputs as inputs).
 *)
Upstream(n) == {u \in Nodes : <<u, n>> \in Edges}

(*
 * UpstreamIn(n, E): Upstream of n in edge set E (used for subgraphs).
 *)
UpstreamIn(n, E) == {u \in Nodes : <<u, n>> \in E}

(*
 * Reachability: All nodes reachable from start set following edges in E.
 * Computed as a fixed point.
 *)
RECURSIVE ReachableFromSet(_, _)
ReachableFromSet(startSet, E) ==
    LET oneStep == {v \in Nodes : \E u \in startSet : <<u, v>> \in E}
        newNodes == oneStep \ startSet
    IN IF newNodes = {}
       THEN startSet
       ELSE ReachableFromSet(startSet \cup newNodes, E)

ReachableFrom(n, E) == ReachableFromSet({n}, E)

(*
 * Reverse edges to compute "can reach" relation.
 *)
ReverseEdges(E) == {<<b, a>> : <<a, b>> \in E}

ReachableTo(n, E) == ReachableFrom(n, ReverseEdges(E))

(*
 * SCC: Strongly connected component containing node n in edge set E.
 * A node v is in n's SCC iff n can reach v AND v can reach n.
 *)
SCCOf(n, E) == ReachableFrom(n, E) \cap ReachableTo(n, E)

(*
 * AllSCCs: Set of all SCCs in edge set E.
 *)
AllSCCs(E) == {SCCOf(n, E) : n \in Nodes}

(*
 * CondensationEdge: Is there an edge from SCC s1 to SCC s2?
 * True iff some node in s1 has an edge to some node in s2, and s1 != s2.
 *)
HasCondensationEdge(s1, s2, E) ==
    /\ s1 # s2
    /\ \E u \in s1, v \in s2 : <<u, v>> \in E

(*
 * IsLeafSCC: An SCC is a leaf if it has no outgoing edges in the condensation.
 *)
IsLeafSCC(scc, E) ==
    ~\E s2 \in AllSCCs(E) : HasCondensationEdge(scc, s2, E)

(*
 * LeafSCCs: All leaf SCCs in edge set E.
 *)
LeafSCCs(E) == {scc \in AllSCCs(E) : IsLeafSCC(scc, E)}

(* ===== STATE VARIABLES ===== *)

VARIABLES
    generation,      \* generation[n] = current generation of node n
    lastSeenGen,     \* lastSeenGen[n][u] = generation of upstream u when n last evaluated
    runningNode,     \* The node currently evaluating, or NoNode if none
    resolutionQueue, \* Set of nodes that have been demanded (need resolution)
    terminated       \* Has the computation terminated?

vars == <<generation, lastSeenGen, runningNode, resolutionQueue, terminated>>

(*
 * NoNode: Sentinel value for "no node is running".
 * We use -1 since Nodes are natural numbers >= 0.
 *)
NoNode == -1

(* ===== GENERATION ORDERING ===== *)

(*
 * Generations in Flowno track how many times a node has been evaluated.
 * 
 * In the real implementation:
 *   - None: Never evaluated (smallest in ordering)
 *   - (0,): First evaluation
 *   - (1,): Second evaluation
 *   - etc.
 * 
 * The ordering is: None < (0,) < (1,) < (2,) < ...
 * 
 * For model checking, we simplify to integers:
 *   - NoneGen (-1): Never evaluated
 *   - 0, 1, 2, ...: Evaluation count
 * 
 * This preserves the ordering: -1 < 0 < 1 < 2 < ...
 *)

NoneGen == -1  \* Sentinel for "never evaluated"

(*
 * GenLessThan: Is generation g1 strictly less than g2?
 * This is just integer < since we encode None as -1.
 *)
GenLessThan(g1, g2) == g1 < g2

(*
 * GenLeq: Is g1 <= g2?
 *)
GenLeq(g1, g2) == g1 <= g2

(* ===== TYPE INVARIANTS ===== *)

(*
 * Valid generations are: NoneGen (-1) or 0..MaxGeneration
 *)
ValidGeneration == {NoneGen} \cup (0..MaxGeneration)

TypeOK ==
    /\ generation \in [Nodes -> ValidGeneration]
    /\ lastSeenGen \in [Nodes -> [Nodes -> ValidGeneration]]
    /\ runningNode \in Nodes \cup {NoNode}
    /\ resolutionQueue \in SUBSET Nodes
    /\ terminated \in BOOLEAN

(* ===== STALENESS ===== *)

(*
 * IsEdgeStale: Edge <<u, d>> is stale when d's view of u is outdated.
 * 
 * The downstream node d has cached what generation of u it last saw.
 * The edge is stale if u's current generation is strictly greater than
 * what d has seen.
 * 
 * Note: If u has NoneGen (never evaluated), and d has lastSeenGen = NoneGen,
 * then NoneGen < NoneGen = FALSE, so the edge is NOT stale.
 * This is correct: if upstream never ran, downstream can't have stale data
 * from it - it has NO data, which is a different condition handled by
 * "upstream needs to run first".
 *)
IsEdgeStale(u, d) ==
    /\ <<u, d>> \in Edges
    /\ GenLessThan(lastSeenGen[d][u], generation[u])

(*
 * StaleEdges: All edges where downstream hasn't seen upstream's current output.
 *)
StaleEdges == {<<u, d>> \in Edges : IsEdgeStale(u, d)}

(*
 * IsNodeStale: A node is stale if any of its incoming edges are stale.
 *)
IsNodeStale(n) == \E u \in Upstream(n) : IsEdgeStale(u, n)

(*
 * HasProducedOutput: A node has produced output at least once.
 *)
HasProducedOutput(n) == generation[n] # NoneGen

(*
 * UpstreamReady: All upstream nodes have produced output.
 * A node can only evaluate if all its inputs are available.
 *)
UpstreamReady(n) == \A u \in Upstream(n) : HasProducedOutput(u)

(*
 * CanEvaluate: A node can evaluate if:
 *   - All its upstreams have produced output (inputs available)
 *   - It's not stale (OR we're in resolution mode breaking a cycle)
 * 
 * For simple evaluation: all inputs ready AND inputs are fresh.
 *)
CanEvaluateFresh(n) == UpstreamReady(n) /\ ~IsNodeStale(n)

(*
 * StaleNodes: All nodes with at least one stale input.
 *)
StaleNodes == {n \in Nodes : IsNodeStale(n)}

(* ===== RESOLUTION ALGORITHM (Approach A: Explicit SCC) ===== *)

(*
 * The resolution algorithm finds which nodes to evaluate.
 * 
 * When a node n is demanded:
 *   1. Compute the "stale subgraph" - edges where data is outdated
 *   2. Compute SCCs of the stale subgraph
 *   3. Build the condensation DAG (DAG of SCCs)
 *   4. Find leaf SCCs - these have no stale dependencies outside themselves
 *   5. Pick any node from each leaf SCC to evaluate
 * 
 * Why leaf SCCs? A leaf SCC contains nodes that either:
 *   - Have no stale inputs (safe to evaluate)
 *   - Form a cycle where all staleness is internal (must pick one to break cycle)
 *)

(*
 * LeafSCCsOfStaleGraph: The leaf SCCs when restricted to stale edges.
 *)
LeafSCCsOfStaleGraph == LeafSCCs(StaleEdges)

(*
 * NodesToEvaluate: Nodes that should be evaluated next.
 * 
 * From each leaf SCC of the stale graph, we can pick any node.
 * We pick the minimum (arbitrary but deterministic for spec clarity).
 *)
NodesToEvaluate ==
    {CHOOSE n \in scc : \A m \in scc : n <= m : scc \in LeafSCCsOfStaleGraph}

(* ===== INITIAL STATE ===== *)

Init ==
    /\ generation = [n \in Nodes |-> NoneGen]
    /\ lastSeenGen = [n \in Nodes |-> [u \in Nodes |-> NoneGen]]
    /\ runningNode = NoNode
    /\ resolutionQueue = {}
    /\ terminated = FALSE

(* ===== ACTIONS ===== *)

(*
 * Demand: Request the output of a node.
 * This adds the node to the resolution queue, signaling that its output is needed.
 *)
Demand(n) ==
    /\ ~terminated
    /\ runningNode = NoNode
    /\ n \notin resolutionQueue
    /\ resolutionQueue' = resolutionQueue \cup {n}
    /\ UNCHANGED <<generation, lastSeenGen, runningNode, terminated>>

(*
 * Resolve: Pick a node from a leaf SCC and begin evaluating it.
 * 
 * Preconditions:
 *   - No node is currently running
 *   - There's a demanded node that has stale inputs requiring resolution
 *   - The chosen node is from a leaf SCC (safe to evaluate)
 *)
Resolve ==
    /\ ~terminated
    /\ runningNode = NoNode
    /\ resolutionQueue # {}
    /\ StaleEdges # {}
    /\ \E n \in NodesToEvaluate :
        /\ runningNode' = n
        /\ UNCHANGED <<generation, lastSeenGen, resolutionQueue, terminated>>

(*
 * StartFreshNode: Begin evaluating a demanded node that is ready.
 * 
 * A node is ready to evaluate if:
 *   - All upstream nodes have produced output (inputs available)
 *   - It's not stale (all inputs are current)
 * 
 * This is the "simple case" where no resolution is needed.
 *)
StartFreshNode ==
    /\ ~terminated
    /\ runningNode = NoNode
    /\ \E n \in resolutionQueue :
        /\ CanEvaluateFresh(n)
        /\ runningNode' = n
        /\ UNCHANGED <<generation, lastSeenGen, resolutionQueue, terminated>>

(*
 * CompleteNode: A running node finishes evaluation.
 * 
 * Effects:
 *   - Increment the node's generation (it produced new output)
 *     First evaluation: NoneGen (-1) + 1 = 0
 *     Subsequent: 0 -> 1 -> 2 -> ...
 *   - Update lastSeenGen to reflect that it read all current upstream values
 *   - Remove from queue if it was demanded
 *   - Release the running slot
 *)
CompleteNode ==
    /\ ~terminated
    /\ runningNode # NoNode
    /\ generation[runningNode] < MaxGeneration  \* Bound for model checking
    /\ LET n == runningNode
           newGen == generation[n] + 1  \* NoneGen + 1 = 0 for first eval
       IN /\ generation' = [generation EXCEPT ![n] = newGen]
          /\ lastSeenGen' = [lastSeenGen EXCEPT ![n] = 
                               [u \in Nodes |-> IF u \in Upstream(n)
                                                THEN generation[u]
                                                ELSE @[u]]]
          \* Node completed - remove from queue if it was demanded
          /\ resolutionQueue' = resolutionQueue \ {n}
          /\ runningNode' = NoNode
          /\ UNCHANGED terminated

(*
 * Terminate: End the computation when all demands are satisfied.
 *)
Terminate ==
    /\ ~terminated
    /\ runningNode = NoNode
    /\ resolutionQueue = {}
    /\ terminated' = TRUE
    /\ UNCHANGED <<generation, lastSeenGen, runningNode, resolutionQueue>>

(* ===== SPECIFICATION ===== *)

Next ==
    \/ \E n \in Nodes : Demand(n)
    \/ Resolve
    \/ StartFreshNode
    \/ CompleteNode
    \/ Terminate

Spec == Init /\ [][Next]_vars

(* ===== INVARIANTS ===== *)

(*
 * NoStaleOutputUsed: When a node completes, all its inputs were fresh.
 * This is guaranteed by the resolution algorithm picking leaf SCCs.
 *)
NoStaleOutputUsed ==
    runningNode # NoNode => 
        \A u \in Upstream(runningNode) : lastSeenGen[runningNode][u] = generation[u]
        
(* Note: The above is NOT quite right - need to think about when to check this *)

(*
 * Progress: If there are demands and no node is running, something can run.
 *)
CanMakeProgress ==
    (runningNode = NoNode /\ resolutionQueue # {}) =>
        \/ \E n \in resolutionQueue : ~IsNodeStale(n)  \* Fresh node can start
        \/ StaleEdges # {}  \* Need to resolve, and Resolve is enabled

(*
 * NoDeadlock: The system can always make progress unless terminated.
 *)
NoDeadlock ==
    terminated \/ ENABLED Next

(* ===== DEBUG: Check if Resolve action is ever used ===== *)

(*
 * ResolveNeverUsed: This will FAIL if Resolve action ever fires.
 * Use this to verify the SCC-based resolution is being exercised.
 *)
ResolveNeverUsed ==
    ~ENABLED Resolve

=============================================================================
