------------------------------ MODULE EventLoop ------------------------------
(*
 * Formal model of Flowno's EventLoop with AsyncQueue support.
 * EXTENDS EventLoopBasic with queue operations.
 * 
 * Maps to Python:
 *   AsyncQueue.get()  → YieldGet, blocks if empty, wakes when item available
 *   AsyncQueue.put()  → YieldPut, blocks if full, wakes when space available  
 *   AsyncQueue.close() → CloseQueue, wakes all waiters with exception
 *   
 * Queue model:
 *   - Queues are identified by natural numbers 0..MaxQueueId
 *   - Each queue has: item count, max size (None = unbounded), closed flag
 *   - We track item COUNT not actual items (sufficient for deadlock analysis)
 *)
EXTENDS EventLoopBasic

CONSTANT MaxQueueId   \* Bounds state space: queues are 0..MaxQueueId
CONSTANT MaxQueueSize \* Max items per queue (for bounded queues)

Queues == 0..MaxQueueId

(* ===== ADDITIONAL TASK STATES ===== *)
(*
 * Tasks can also be:
 *   - waitingGet[q]: Blocked on queue q waiting for item
 *   - waitingPut[q]: Blocked on queue q waiting for space
 *)

WaitingGet == "waitingGet"
WaitingPut == "waitingPut"

(* ===== QUEUE VARIABLES ===== *)

VARIABLES
    queueItems,    \* Queue ID -> number of items currently in queue
    queueMaxSize,  \* Queue ID -> max size (0 means unbounded)
    queueClosed,   \* Queue ID -> boolean, whether queue is closed
    getWaiters,    \* Queue ID -> set of tasks waiting to get
    putWaiters     \* Queue ID -> set of tasks waiting to put

queueVars == <<queueItems, queueMaxSize, queueClosed, getWaiters, putWaiters>>
allVars == <<taskState, joinWaiters, queueItems, queueMaxSize, queueClosed, getWaiters, putWaiters>>

(* ===== EXTENDED STATE PREDICATES ===== *)

IsWaitingGet(t) == taskState[t].state = WaitingGet
IsWaitingPut(t) == taskState[t].state = WaitingPut

\* Queue the task is waiting on (only valid if IsWaitingGet or IsWaitingPut)
WaitQueue(t) == taskState[t].queue

\* Override IsBlocked to include queue waits
IsBlockedExt(t) == 
    \/ taskState[t].state \in {Sleeping, Joining}
    \/ IsWaitingGet(t)
    \/ IsWaitingPut(t)

\* Override IsAlive - queue-waiting tasks are alive
IsAliveExt(t) == Exists(t) /\ taskState[t].state \notin {Done, Error}

\* Queue has space (unbounded or below max)
HasSpace(q) == 
    \/ queueMaxSize[q] = 0  \* 0 means unbounded
    \/ queueItems[q] < queueMaxSize[q]

\* Queue has items
HasItems(q) == queueItems[q] > 0

\* Queue is open
IsOpen(q) == ~queueClosed[q]

(* ===== EXTENDED TYPE INVARIANT ===== *)

TypeOKExt ==
    /\ TypeOK  \* Base type invariant (but we need to extend taskState domain)
    /\ queueItems \in [Queues -> Nat]
    /\ queueMaxSize \in [Queues -> Nat]  \* 0 = unbounded
    /\ queueClosed \in [Queues -> BOOLEAN]
    /\ getWaiters \in [Queues -> SUBSET Tasks]
    /\ putWaiters \in [Queues -> SUBSET Tasks]

\* Full type invariant including extended task states
TypeOKFull ==
    /\ taskState \in [Tasks -> 
        [state: {Nonexistent}] \cup
        [state: {Ready}] \cup
        [state: {Running}] \cup
        [state: {Sleeping}] \cup
        [state: {Joining}, target: Tasks] \cup
        [state: {Done}] \cup
        [state: {Error}] \cup
        [state: {WaitingGet}, queue: Queues] \cup
        [state: {WaitingPut}, queue: Queues]]
    /\ joinWaiters \in [Tasks -> SUBSET Tasks]
    /\ queueItems \in [Queues -> 0..MaxQueueSize]
    /\ queueMaxSize \in [Queues -> 0..MaxQueueSize]  \* 0 = unbounded
    /\ queueClosed \in [Queues -> BOOLEAN]
    /\ getWaiters \in [Queues -> SUBSET Tasks]
    /\ putWaiters \in [Queues -> SUBSET Tasks]

(* ===== EXTENDED INITIAL STATE ===== *)

InitExt ==
    /\ Init  \* Base initial state
    /\ queueItems = [q \in Queues |-> 0]
    /\ queueMaxSize = [q \in Queues |-> MaxQueueSize]  \* All bounded by default
    /\ queueClosed = [q \in Queues |-> FALSE]
    /\ getWaiters = [q \in Queues |-> {}]
    /\ putWaiters = [q \in Queues |-> {}]

(* ===== QUEUE ACTIONS ===== *)

(*
 * YieldGetImmediate: A running task gets an item from a non-empty queue.
 *
 * Python: task yields QueueGetCommand on queue with items.
 *
 * The running task t wants an item from open queue q that has items.
 *
 * When some task, waiter, is put-waiting on q:
 *   That waiter was blocked trying to add an item. Now waiter' is ready
 *   (no longer put-waiting), and both t' and waiter' are schedulable.
 *   The queue depth stays the same - we took one item but waiter's item
 *   takes its place.
 *
 * When no task is put-waiting on q:
 *   The queue simply has one fewer item, and t' is ready.
 *)
YieldGetImmediate(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ HasItems(q)
    /\ IF putWaiters[q] # {}
       THEN \E waiter \in putWaiters[q] :
            /\ putWaiters' = [putWaiters EXCEPT ![q] = @ \ {waiter}]
            /\ taskState' = [taskState EXCEPT 
                ![t] = [state |-> Ready],
                ![waiter] = [state |-> Ready]]
            /\ queueItems' = [queueItems EXCEPT ![q] = @]
       ELSE /\ putWaiters' = putWaiters
            /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
            /\ queueItems' = [queueItems EXCEPT ![q] = @ - 1]
    /\ UNCHANGED <<joinWaiters, queueMaxSize, queueClosed, getWaiters>>

(*
 * YieldGetBlocks: A running task waits for an item from an empty queue.
 *
 * Python: task yields QueueGetCommand on empty queue.
 *
 * The running task t wants an item from open queue q, but q is empty.
 * Task t' becomes get-waiting on q. When another task eventually puts
 * an item, t can be woken (via YieldPutImmediate).
 *)
YieldGetBlocks(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ ~HasItems(q)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> WaitingGet, queue |-> q]]
    /\ getWaiters' = [getWaiters EXCEPT ![q] = @ \cup {t}]
    /\ UNCHANGED <<joinWaiters, queueItems, queueMaxSize, queueClosed, putWaiters>>

(*
 * YieldPutImmediate: A running task puts an item into a queue with space.
 *
 * Python: task yields QueuePutCommand on queue with space.
 *
 * The running task t wants to put an item into open queue q that has space.
 *
 * When some task, waiter, is get-waiting on q:
 *   That waiter was blocked waiting for an item. The item goes directly
 *   to waiter - so waiter' is ready (no longer get-waiting), t' is ready,
 *   and the queue depth stays the same.
 *
 * When no task is get-waiting on q:
 *   The item goes into the queue, so q has one more item, and t' is ready.
 *)
YieldPutImmediate(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ HasSpace(q)
    /\ IF getWaiters[q] # {}
       THEN \E waiter \in getWaiters[q] :
            /\ getWaiters' = [getWaiters EXCEPT ![q] = @ \ {waiter}]
            /\ taskState' = [taskState EXCEPT 
                ![t] = [state |-> Ready],
                ![waiter] = [state |-> Ready]]
            /\ UNCHANGED queueItems
       ELSE /\ getWaiters' = getWaiters
            /\ taskState' = [taskState EXCEPT ![t] = [state |-> Ready]]
            /\ queueItems' = [queueItems EXCEPT ![q] = @ + 1]
    /\ UNCHANGED <<joinWaiters, queueMaxSize, queueClosed, putWaiters>>

(*
 * YieldPutBlocks: A running task waits to put into a full queue.
 *
 * Python: task yields QueuePutCommand on full queue.
 *
 * The running task t wants to put an item into open queue q, but q is full.
 * Task t' becomes put-waiting on q. When another task eventually gets
 * an item (making space), t can be woken (via YieldGetImmediate).
 *)
YieldPutBlocks(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ ~HasSpace(q)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> WaitingPut, queue |-> q]]
    /\ putWaiters' = [putWaiters EXCEPT ![q] = @ \cup {t}]
    /\ UNCHANGED <<joinWaiters, queueItems, queueMaxSize, queueClosed, getWaiters>>

(*
 * YieldGetClosed: A running task tries to get from a closed empty queue.
 *
 * Python: task yields QueueGetCommand on closed queue, receives QueueClosedError.
 *
 * The running task t tries to get from queue q, but q is closed and empty.
 * Task t' enters error state (representing the QueueClosedError exception).
 *)
YieldGetClosed(t, q) ==
    /\ IsRunning(t)
    /\ queueClosed[q]
    /\ ~HasItems(q)
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Error]]
    /\ UNCHANGED <<joinWaiters, queueVars>>

(*
 * YieldPutClosed: A running task tries to put into a closed queue.
 *
 * Python: task yields QueuePutCommand on closed queue, receives QueueClosedError.
 *
 * The running task t tries to put into queue q, but q is closed.
 * Task t' enters error state (representing the QueueClosedError exception).
 *)
YieldPutClosed(t, q) ==
    /\ IsRunning(t)
    /\ queueClosed[q]
    /\ taskState' = [taskState EXCEPT ![t] = [state |-> Error]]
    /\ UNCHANGED <<joinWaiters, queueVars>>

(*
 * CloseQueue: A running task closes an open queue.
 *
 * Python: task yields QueueCloseCommand.
 *
 * The running task t closes queue q. Queue q' is closed.
 * Task t' becomes ready (the close succeeded).
 *
 * Every task that was get-waiting on q enters error state - they were
 * waiting for items that will never come. Similarly, every task that
 * was put-waiting on q enters error state - they can't put into a
 * closed queue. No task remains waiting on q'.
 *)
CloseQueue(t, q) ==
    /\ IsRunning(t)
    /\ IsOpen(q)
    /\ queueClosed' = [queueClosed EXCEPT ![q] = TRUE]
    /\ taskState' = [task \in Tasks |->
        IF task = t THEN [state |-> Ready]
        ELSE IF task \in getWaiters[q] THEN [state |-> Error]
        ELSE IF task \in putWaiters[q] THEN [state |-> Error]
        ELSE taskState[task]]
    /\ getWaiters' = [getWaiters EXCEPT ![q] = {}]
    /\ putWaiters' = [putWaiters EXCEPT ![q] = {}]
    /\ UNCHANGED <<joinWaiters, queueItems, queueMaxSize>>

(* ===== EXTENDED NEXT STATE RELATION ===== *)

\* Base actions from EventLoopBasic, extended to preserve queueVars
NextExt ==
    \* Base actions (inherited from EXTENDS, just add UNCHANGED queueVars)
    \/ \E t \in Tasks : Schedule(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : YieldReady(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : YieldSleep(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : WakeFromSleep(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : Complete(t) /\ UNCHANGED queueVars
    \/ \E t \in Tasks : Fail(t) /\ UNCHANGED queueVars
    \/ \E t, target \in Tasks : YieldJoin(t, target) /\ UNCHANGED queueVars
    \/ \E t, target \in Tasks : JoinComplete(t, target) /\ UNCHANGED queueVars
    \/ \E t, target \in Tasks : JoinAlreadyDone(t, target) /\ UNCHANGED queueVars
    \/ \E t, newTask \in Tasks : Spawn(t, newTask) /\ UNCHANGED queueVars
    \* Queue actions
    \/ \E t \in Tasks, q \in Queues : YieldGetImmediate(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldGetBlocks(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldPutImmediate(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldPutBlocks(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldGetClosed(t, q)
    \/ \E t \in Tasks, q \in Queues : YieldPutClosed(t, q)
    \/ \E t \in Tasks, q \in Queues : CloseQueue(t, q)

SpecExt == InitExt /\ [][NextExt]_allVars

(* ===== QUEUE INVARIANTS ===== *)

(*
 * GetWaitersConsistent: If queue has items, no task should be waiting on Get.
 * This verifies the event loop correctly wakes getters when items are available.
 *)
GetWaitersConsistent ==
    \A q \in Queues : HasItems(q) => getWaiters[q] = {}

(*
 * PutWaitersConsistent: If queue has space, no task should be waiting on Put.
 * This verifies the event loop correctly wakes putters when space is available.
 *)
PutWaitersConsistent ==
    \A q \in Queues : HasSpace(q) => putWaiters[q] = {}

(*
 * WaiterStateConsistent: Tasks in waiter sets must be in corresponding state.
 *)
WaiterStateConsistent ==
    /\ \A q \in Queues : \A t \in getWaiters[q] : 
        IsWaitingGet(t) /\ WaitQueue(t) = q
    /\ \A q \in Queues : \A t \in putWaiters[q] : 
        IsWaitingPut(t) /\ WaitQueue(t) = q

(*
 * NoZombieQueueWaiters: If task is waiting on queue, it must be in waiter set.
 *)
NoZombieQueueWaiters ==
    \A t \in Tasks :
        /\ IsWaitingGet(t) => t \in getWaiters[WaitQueue(t)]
        /\ IsWaitingPut(t) => t \in putWaiters[WaitQueue(t)]

(*
 * ClosedQueueNoWaiters: Closed queues should have no waiters.
 * (They're all woken with errors when queue closes)
 *)
ClosedQueueNoWaiters ==
    \A q \in Queues : queueClosed[q] => 
        (getWaiters[q] = {} /\ putWaiters[q] = {})

(* ===== EXTENDED NODEADLOCK ===== *)

(*
 * CanMakeProgressExt includes queue waiters that can be woken.
 * But per our discussion: if queue invariants hold, waiters CAN'T be woken
 * (because if they could, they already would have been).
 * So we just check if any task is ready/running/sleeping/joinable.
 * Queue-blocked tasks with no progress available = deadlock.
 *)
CanMakeProgressExt ==
    \/ \E t \in Tasks : IsReady(t)
    \/ \E t \in Tasks : IsRunning(t)
    \/ \E t \in Tasks : IsSleeping(t)
    \/ \E t \in Tasks : IsJoining(t) /\ IsTerminal(JoinTarget(t))

NoDeadlockExt ==
    LET aliveTasks == {t \in Tasks : IsAliveExt(t)}
    IN aliveTasks # {} => CanMakeProgressExt

=============================================================================
